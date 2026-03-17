"""
Verlytax OS v4 — Billing & Fee Collection Routes
Fee always on GROSS revenue BEFORE factoring discount. Zero exceptions.
"""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db import get_db, Carrier, Load, LoadStatus
from app.iron_rules import check_load, get_rpm_tier, can_release_bol
from app.services import calculate_fee, charge_carrier_fee, nova_alert_ceo, nova_sms

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class LoadCreate(BaseModel):
    carrier_mc: str
    broker_name: str
    broker_contact: str
    origin_city: str
    origin_state: str
    destination_city: str
    destination_state: str
    total_miles: float
    deadhead_miles: float
    weight_lbs: float
    rate_total: float
    rate_per_mile: float
    pickup_date: datetime
    delivery_date: datetime
    has_extra_services: bool = False

class BolReleaseRequest(BaseModel):
    load_id: int
    delivery_confirmed: bool


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/load/check")
async def check_load_rules(data: LoadCreate):
    """
    Pre-booking Iron Rules check — run BEFORE touching any load.
    Returns pass/fail with violation details.
    """
    result = check_load(
        origin_state=data.origin_state,
        destination_state=data.destination_state,
        rate_per_mile=data.rate_per_mile,
        deadhead_miles=data.deadhead_miles,
        total_miles=data.total_miles,
        weight_lbs=data.weight_lbs,
    )
    rpm_tier = get_rpm_tier(data.rate_per_mile)
    return {
        "passed": result.passed,
        "rpm_tier": rpm_tier,
        "requires_counter": result.requires_counter,
        "violations": [
            {"rule": v.rule_name, "message": v.message, "action": v.action}
            for v in result.violations
        ],
    }


@router.post("/load/book")
async def book_load(data: LoadCreate, db: AsyncSession = Depends(get_db)):
    """
    Book a load after Iron Rules check passes.
    Calculates Verlytax fee on gross revenue.
    """
    # Verify carrier exists and is active
    carrier_result = await db.execute(select(Carrier).where(Carrier.mc_number == data.carrier_mc))
    carrier = carrier_result.scalar_one_or_none()
    if not carrier:
        raise HTTPException(404, "Carrier not found in verlytax.db")
    if carrier.status not in ("active", "trial"):
        raise HTTPException(400, f"Carrier status '{carrier.status}' — cannot dispatch.")

    # Iron Rules check
    check = check_load(
        origin_state=data.origin_state,
        destination_state=data.destination_state,
        rate_per_mile=data.rate_per_mile,
        deadhead_miles=data.deadhead_miles,
        total_miles=data.total_miles,
        weight_lbs=data.weight_lbs,
    )
    if not check.passed:
        return {
            "status": "rejected",
            "reason": check.rejection_reason,
            "violations": [{"rule": v.rule_name, "message": v.message} for v in check.violations if v.action == "REJECT"],
        }

    # Calculate fee
    fee_info = calculate_fee(
        gross_load_revenue=data.rate_total,
        carrier_active_since=carrier.active_since,
        trial_start=carrier.trial_start_date,
        has_extra_services=data.has_extra_services,
    )

    load = Load(
        carrier_mc=data.carrier_mc,
        broker_name=data.broker_name,
        broker_contact=data.broker_contact,
        origin_city=data.origin_city,
        origin_state=data.origin_state,
        destination_city=data.destination_city,
        destination_state=data.destination_state,
        total_miles=data.total_miles,
        deadhead_miles=data.deadhead_miles,
        weight_lbs=data.weight_lbs,
        rate_total=data.rate_total,
        rate_per_mile=data.rate_per_mile,
        pickup_date=data.pickup_date,
        delivery_date=data.delivery_date,
        verlytax_fee=fee_info["fee_amount"],
        status=LoadStatus.BOOKED,
    )
    db.add(load)
    await db.commit()
    await db.refresh(load)

    return {
        "status": "booked",
        "load_id": load.id,
        "route": f"{data.origin_city}, {data.origin_state} → {data.destination_city}, {data.destination_state}",
        "rate_per_mile": data.rate_per_mile,
        "rpm_tier": get_rpm_tier(data.rate_per_mile),
        "verlytax_fee": fee_info,
        "requires_counter": check.requires_counter,
    }


@router.post("/load/{load_id}/deliver")
async def confirm_delivery(load_id: int, pod_collected: bool = True, db: AsyncSession = Depends(get_db)):
    """Mark load as delivered and collect POD. Trigger fee invoicing."""
    result = await db.execute(select(Load).where(Load.id == load_id))
    load = result.scalar_one_or_none()
    if not load:
        raise HTTPException(404, "Load not found.")

    load.status = LoadStatus.DELIVERED
    load.pod_collected = pod_collected
    load.invoice_sent_at = datetime.utcnow()
    await db.commit()

    return {
        "status": "delivered",
        "load_id": load_id,
        "pod_collected": pod_collected,
        "verlytax_fee_due": load.verlytax_fee,
        "invoice_sent_at": load.invoice_sent_at,
        "next_step": "Collect Verlytax fee before releasing payment to carrier.",
    }


@router.post("/load/bol-release")
async def release_bol(data: BolReleaseRequest, db: AsyncSession = Depends(get_db)):
    """
    Iron Rule 11: Never release BOL before delivery confirmed.
    """
    if not can_release_bol(data.delivery_confirmed):
        raise HTTPException(403, "Iron Rule 11 violation: Cannot release BOL before delivery is confirmed.")

    result = await db.execute(select(Load).where(Load.id == data.load_id))
    load = result.scalar_one_or_none()
    if not load:
        raise HTTPException(404, "Load not found.")

    load.bol_released = True
    await db.commit()
    return {"status": "bol_released", "load_id": data.load_id}


@router.post("/collect-fee/{load_id}")
async def collect_fee(load_id: int, db: AsyncSession = Depends(get_db)):
    """
    Charge the Verlytax dispatch fee via Stripe.
    Fee collected on GROSS revenue BEFORE factoring.
    """
    result = await db.execute(select(Load).where(Load.id == load_id))
    load = result.scalar_one_or_none()
    if not load:
        raise HTTPException(404, "Load not found.")
    if load.fee_collected:
        return {"status": "already_collected", "load_id": load_id}

    carrier_result = await db.execute(select(Carrier).where(Carrier.mc_number == load.carrier_mc))
    carrier = carrier_result.scalar_one_or_none()
    if not carrier or not carrier.stripe_customer_id:
        raise HTTPException(400, "Carrier has no Stripe payment method on file.")

    amount_cents = int(load.verlytax_fee * 100)
    charge = charge_carrier_fee(
        stripe_customer_id=carrier.stripe_customer_id,
        amount_cents=amount_cents,
        description=f"Verlytax dispatch fee — Load #{load_id} | MC#{load.carrier_mc}",
    )

    if charge.get("status") == "charged":
        load.fee_collected = True
        load.status = LoadStatus.PAID
        await db.commit()
        return {"status": "collected", "amount": load.verlytax_fee, "load_id": load_id}

    # Failed payment — suspend carrier + alert Delta
    if carrier.phone:
        nova_sms(carrier.phone, f"Verlytax fee payment failed for load #{load_id}. Please update your payment method. Reply or call ops@verlytax.com")
    nova_alert_ceo(
        subject=f"PAYMENT FAILED — MC#{load.carrier_mc}",
        body=f"Fee ${load.verlytax_fee:.2f} failed for Load #{load_id}.\nStripe error: {charge.get('reason')}",
    )
    carrier.status = "suspended"
    await db.commit()

    return {"status": "failed", "reason": charge.get("reason"), "carrier_suspended": True}


@router.get("/loads/{mc_number}")
async def get_carrier_loads(mc_number: str, db: AsyncSession = Depends(get_db)):
    """Get all loads for a carrier from verlytax.db."""
    result = await db.execute(select(Load).where(Load.carrier_mc == mc_number))
    loads = result.scalars().all()
    return [
        {
            "load_id": l.id,
            "route": f"{l.origin_city}, {l.origin_state} → {l.destination_city}, {l.destination_state}",
            "status": l.status,
            "rate_per_mile": l.rate_per_mile,
            "rate_total": l.rate_total,
            "verlytax_fee": l.verlytax_fee,
            "fee_collected": l.fee_collected,
            "pickup_date": l.pickup_date,
            "delivery_date": l.delivery_date,
        }
        for l in loads
    ]
