"""
Verlytax OS v4 — Escalation & Dispute Resolution Routes
Section 5 & 6 of Erin system prompt.
"""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db import get_db, EscalationLog, BlockedBroker
from app.services import nova_alert_ceo, nova_sms

router = APIRouter()

# Escalation thresholds
ESCALATE_MONEY_THRESHOLD = 500.0    # Any decision over $500 → Delta
WRITE_OFF_THRESHOLD = 500.0          # Write-off at $500 or less
MINIMUM_SETTLE_PCT = 0.83            # Negotiate min 83% of invoice
DISPUTE_TIMEOUT_HOURS = 48


# ── Schemas ───────────────────────────────────────────────────────────────────

class EscalationCreate(BaseModel):
    carrier_mc: Optional[str] = None
    load_id: Optional[int] = None
    issue_type: str   # e.g. "payment_dispute", "carrier_leaving", "legal", "broker_bad_faith"
    description: str
    amount: Optional[float] = None

class DisputeAction(BaseModel):
    escalation_id: int
    action: str        # "dispute" | "negotiate" | "write_off"
    notes: Optional[str] = None

class BrokerBlockRequest(BaseModel):
    broker_name: str
    mc_number: Optional[str] = None
    reason: str
    dat_file: bool = False


# ── Auto-escalation rules ─────────────────────────────────────────────────────

ALWAYS_ESCALATE_TYPES = {
    "carrier_leaving",
    "legal_document",
    "new_market_launch",
    "bank_transfer_2fa",
    "ad_spend_increase",
    "bad_faith_broker_confirm",
    "unknown",
}

ERIN_HANDLES_ALONE = {
    "iron_rule_rejection",
    "standard_onboarding",
    "invoice_generation",
    "fee_collection_standard",
    "lead_outreach",
    "daily_report",
    "win_back",
}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/create")
async def create_escalation(data: EscalationCreate, db: AsyncSession = Depends(get_db)):
    """
    Create an escalation log entry. Auto-routes to Delta if required.
    """
    needs_delta = (
        data.issue_type in ALWAYS_ESCALATE_TYPES
        or (data.amount and data.amount > ESCALATE_MONEY_THRESHOLD)
    )

    log = EscalationLog(
        carrier_mc=data.carrier_mc,
        load_id=data.load_id,
        issue_type=data.issue_type,
        description=data.description,
        amount=data.amount,
        status="escalated_to_delta" if needs_delta else "erin_handling",
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)

    if needs_delta:
        nova_alert_ceo(
            subject=f"ESCALATION: {data.issue_type.upper()} | MC#{data.carrier_mc or 'N/A'}",
            body=(
                f"Issue: {data.description}\n"
                f"Amount: ${data.amount:.2f}" if data.amount else f"Issue: {data.description}"
            ),
        )

    return {
        "escalation_id": log.id,
        "routed_to": "delta" if needs_delta else "erin",
        "status": log.status,
        "note": "Delta alerted via SMS" if needs_delta else "Erin handling independently",
    }


@router.post("/dispute/action")
async def take_dispute_action(data: DisputeAction, db: AsyncSession = Depends(get_db)):
    """
    Step 3 of dispute protocol: Delta decides — DISPUTE / NEGOTIATE / WRITE OFF.
    """
    result = await db.execute(select(EscalationLog).where(EscalationLog.id == data.escalation_id))
    log = result.scalar_one_or_none()
    if not log:
        raise HTTPException(404, "Escalation not found.")

    action = data.action.lower()

    if action == "dispute":
        # Step 4: DAT filing + broker flagged
        log.status = "disputed_dat_filed"
        log.description += f"\n[DISPUTE ACTION] DAT filing initiated. {data.notes or ''}"
        await db.commit()
        return {
            "action": "dispute",
            "next_steps": [
                "File dispute on DAT",
                "Flag broker in system",
                "If 2+ issues → permanent block (bad faith)",
            ],
        }

    elif action == "negotiate":
        # Step 5: Counter at 83% minimum
        if log.amount:
            min_counter = round(log.amount * MINIMUM_SETTLE_PCT, 2)
        else:
            min_counter = None
        log.status = "negotiating"
        log.description += f"\n[NEGOTIATE] Minimum counter: ${min_counter}. {data.notes or ''}"
        await db.commit()
        return {
            "action": "negotiate",
            "minimum_counter_amount": min_counter,
            "note": f"Never settle below 83% of invoice (${min_counter})",
        }

    elif action == "write_off":
        # Step 6: Write off at $500 or less
        if log.amount and log.amount > WRITE_OFF_THRESHOLD:
            raise HTTPException(400, f"Amount ${log.amount:.2f} exceeds write-off threshold of ${WRITE_OFF_THRESHOLD}. Escalate to Delta.")
        log.status = "written_off"
        log.resolved_at = datetime.utcnow()
        log.description += f"\n[WRITE OFF] {data.notes or ''}"
        await db.commit()
        return {"action": "write_off", "amount": log.amount, "status": "written_off"}

    raise HTTPException(400, "Invalid action. Use: dispute | negotiate | write_off")


@router.post("/broker/block")
async def block_broker(data: BrokerBlockRequest, db: AsyncSession = Depends(get_db)):
    """
    Iron Rule 8: Permanently block a bad-faith broker.
    Step 7 of dispute protocol — 2+ issues = permanent block.
    """
    blocked = BlockedBroker(
        broker_name=data.broker_name,
        mc_number=data.mc_number,
        reason=data.reason,
        dat_filed=data.dat_file,
        blocked_by="delta",
    )
    db.add(blocked)
    await db.commit()
    await db.refresh(blocked)

    nova_alert_ceo(
        subject=f"BROKER BLOCKED — {data.broker_name}",
        body=f"Reason: {data.reason}\nDAT Filed: {data.dat_file}\nMC#: {data.mc_number or 'N/A'}",
    )

    return {
        "status": "blocked",
        "broker": data.broker_name,
        "dat_filed": data.dat_file,
        "note": "Broker permanently removed from all load searches.",
    }


@router.get("/blocked-brokers")
async def list_blocked_brokers(db: AsyncSession = Depends(get_db)):
    """Get all blocked brokers from memory_brokers."""
    result = await db.execute(select(BlockedBroker))
    brokers = result.scalars().all()
    return [
        {
            "id": b.id,
            "broker_name": b.broker_name,
            "mc_number": b.mc_number,
            "reason": b.reason,
            "blocked_at": b.blocked_at,
            "dat_filed": b.dat_filed,
        }
        for b in brokers
    ]


@router.get("/open")
async def get_open_escalations(db: AsyncSession = Depends(get_db)):
    """Get all unresolved escalations."""
    result = await db.execute(
        select(EscalationLog).where(EscalationLog.status.notin_(["written_off", "resolved"]))
    )
    logs = result.scalars().all()
    return [
        {
            "id": l.id,
            "issue_type": l.issue_type,
            "carrier_mc": l.carrier_mc,
            "amount": l.amount,
            "status": l.status,
            "description": l.description,
            "created_at": l.created_at,
        }
        for l in logs
    ]
