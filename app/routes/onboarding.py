"""
Verlytax OS v4 — Carrier Onboarding Routes
10-step onboarding flow per Erin system prompt Section 7.
"""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db import get_db, Carrier, CarrierStatus
from app.iron_rules import check_carrier
from app.services import nova_day1_carrier_packet, nova_alert_ceo, fmcsa_lookup
from app.gdrive import create_carrier_drive_folder

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class CarrierCreate(BaseModel):
    mc_number: str
    name: str
    phone: str
    email: str
    dot_number: Optional[str] = None
    ein: Optional[str] = None
    truck_type: str = "dry_van"
    authority_granted_date: Optional[datetime] = None
    factoring_company: Optional[str] = None

class ComplianceUpdate(BaseModel):
    mc_number: str
    clearinghouse_passed: bool
    nds_enrolled: bool
    safety_rating: str
    coi_expiry: Optional[datetime] = None
    auto_liability_amount: Optional[float] = None
    cargo_coverage_amount: Optional[float] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/lead")
async def create_lead(data: CarrierCreate, db: AsyncSession = Depends(get_db)):
    """
    Step 1–2: SDR creates a lead after initial outreach + Retell screening.
    """
    existing = await db.execute(select(Carrier).where(Carrier.mc_number == data.mc_number))
    if existing.scalar_one_or_none():
        raise HTTPException(400, f"Carrier MC#{data.mc_number} already exists.")

    carrier = Carrier(
        mc_number=data.mc_number,
        name=data.name,
        phone=data.phone,
        email=data.email,
        dot_number=data.dot_number,
        ein=data.ein,
        truck_type=data.truck_type,
        authority_granted_date=data.authority_granted_date,
        factoring_company=data.factoring_company,
        status=CarrierStatus.LEAD,
    )
    db.add(carrier)
    await db.commit()
    await db.refresh(carrier)
    return {"status": "lead_created", "carrier_id": carrier.id, "mc_number": carrier.mc_number}


@router.post("/compliance-check")
async def run_compliance_check(data: ComplianceUpdate, db: AsyncSession = Depends(get_db)):
    """
    Step 3: Brain compliance check — Iron Rules enforcer.
    FMCSA / safety / authority age / insurance.
    """
    result = await db.execute(select(Carrier).where(Carrier.mc_number == data.mc_number))
    carrier = result.scalar_one_or_none()
    if not carrier:
        raise HTTPException(404, f"Carrier MC#{data.mc_number} not found.")

    # Run Iron Rules check
    check = check_carrier(
        safety_rating=data.safety_rating,
        authority_granted_date=carrier.authority_granted_date,
        clearinghouse_passed=data.clearinghouse_passed,
        nds_enrolled=data.nds_enrolled,
        is_blocked=carrier.is_blocked,
    )

    # Update compliance fields
    carrier.safety_rating = data.safety_rating
    carrier.clearinghouse_passed = data.clearinghouse_passed
    carrier.clearinghouse_checked_at = datetime.utcnow()
    carrier.nds_enrolled = data.nds_enrolled
    if data.coi_expiry:
        carrier.coi_expiry = data.coi_expiry
    if data.auto_liability_amount:
        carrier.auto_liability_amount = data.auto_liability_amount
    if data.cargo_coverage_amount:
        carrier.cargo_coverage_amount = data.cargo_coverage_amount

    if not check.passed:
        carrier.status = CarrierStatus.BLOCKED
        carrier.is_blocked = True
        carrier.block_reason = "; ".join(v.message for v in check.violations)
        await db.commit()
        # Alert Delta
        nova_alert_ceo(
            subject=f"Carrier REJECTED — MC#{data.mc_number}",
            body=f"Carrier {carrier.name} failed compliance.\n\nReasons:\n{carrier.block_reason}",
        )
        return {
            "status": "rejected",
            "violations": [{"rule": v.rule_name, "message": v.message} for v in check.violations],
        }

    # Passed — activate trial
    carrier.status = CarrierStatus.TRIAL
    carrier.trial_start_date = datetime.utcnow()
    await db.commit()

    return {"status": "approved", "trial_started": True, "mc_number": data.mc_number}


@router.post("/activate-trial")
async def activate_trial(mc_number: str, db: AsyncSession = Depends(get_db)):
    """
    Step 5–6: Activate 7-day free trial + send Day 1 carrier packet via Nova SMS.
    """
    result = await db.execute(select(Carrier).where(Carrier.mc_number == mc_number))
    carrier = result.scalar_one_or_none()
    if not carrier:
        raise HTTPException(404, "Carrier not found.")
    if carrier.status != CarrierStatus.TRIAL:
        raise HTTPException(400, "Carrier must pass compliance check first.")

    sms_result = nova_day1_carrier_packet(
        carrier_phone=carrier.phone,
        carrier_name=carrier.name,
        mc_number=carrier.mc_number,
    )

    # Brain auto-creates Google Drive folder structure for this carrier
    drive_result = create_carrier_drive_folder(
        carrier_name=carrier.name,
        mc_number=carrier.mc_number,
    )

    return {
        "status": "trial_active",
        "trial_start": carrier.trial_start_date,
        "day1_sms": sms_result,
        "drive_folder": drive_result,
        "next_steps": [
            "Day 3: Mid-trial check-in",
            "Day 5: HelloSign service agreement sent to carrier email",
            "Day 7: Trial results + convert offer",
        ],
    }


@router.post("/convert")
async def convert_to_active(mc_number: str, stripe_customer_id: str, db: AsyncSession = Depends(get_db)):
    """
    Step 10: Trial convert — carrier signs agreement, Stripe activated.
    """
    result = await db.execute(select(Carrier).where(Carrier.mc_number == mc_number))
    carrier = result.scalar_one_or_none()
    if not carrier:
        raise HTTPException(404, "Carrier not found.")

    carrier.status = CarrierStatus.ACTIVE
    carrier.active_since = datetime.utcnow()
    carrier.stripe_customer_id = stripe_customer_id
    await db.commit()

    nova_alert_ceo(
        subject=f"New Carrier Converted — MC#{mc_number}",
        body=f"{carrier.name} (MC#{mc_number}) has signed and gone active. Stripe: {stripe_customer_id}",
    )

    return {"status": "active", "mc_number": mc_number, "active_since": carrier.active_since}


@router.get("/carrier/{mc_number}")
async def get_carrier(mc_number: str, db: AsyncSession = Depends(get_db)):
    """Get carrier profile from verlytax.db."""
    result = await db.execute(select(Carrier).where(Carrier.mc_number == mc_number))
    carrier = result.scalar_one_or_none()
    if not carrier:
        raise HTTPException(404, "NO DATA — carrier not found in verlytax.db")
    return {
        "mc_number": carrier.mc_number,
        "name": carrier.name,
        "status": carrier.status,
        "safety_rating": carrier.safety_rating,
        "clearinghouse_passed": carrier.clearinghouse_passed,
        "nds_enrolled": carrier.nds_enrolled,
        "trial_start_date": carrier.trial_start_date,
        "active_since": carrier.active_since,
        "factoring_company": carrier.factoring_company,
        "is_blocked": carrier.is_blocked,
    }


@router.post("/fmcsa-lookup")
async def lookup_fmcsa(mc_number: str):
    """Step 3: Live FMCSA portal check for carrier compliance data."""
    result = await fmcsa_lookup(mc_number)
    return result
