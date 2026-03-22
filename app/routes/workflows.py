"""
Verlytax OS v4 — Multi-Agent Workflow Pipelines
Chains Receptionist, Megan, Nova, and Brain together into automated sequences.
All pipeline runs are logged to automation_logs for full audit trail.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db import get_db, Carrier, CarrierStatus, AutomationLog
from app.services import (
    verify_internal_token,
    run_agent,
    nova_sms,
    nova_alert_ceo,
    log_automation,
)

router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────────────────

class InboundQualifyRequest(BaseModel):
    caller_name: str
    caller_phone: str
    message: str
    mc_number: Optional[str] = None

class OutboundBlastRequest(BaseModel):
    limit: int = 10                         # Max leads to contact in one blast
    context: Optional[str] = None          # Extra context passed to Megan

class ManualTriggerRequest(BaseModel):
    scan_type: str                          # "overdue_loads" | "no_load_carriers" | "stale_leads" | "all"


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _log(db: AsyncSession, agent: str, action_type: str, description: str,
               result: str, carrier_mc: str = None, escalated: bool = False):
    db.add(AutomationLog(
        agent=agent,
        action_type=action_type,
        carrier_mc=carrier_mc,
        description=description,
        result=result,
        escalated_to_delta=escalated,
    ))
    await db.commit()


# ── Pipeline 1: Inbound Qualify → SDR Draft → Nova Send ───────────────────────

@router.post("/inbound-qualify")
async def workflow_inbound_qualify(
    data: InboundQualifyRequest,
    x_internal_token: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Full inbound pipeline:
      1. Receptionist qualifies the caller
      2. If they pass — Megan auto-drafts a follow-up SMS
      3. Nova sends the follow-up immediately
      4. Lead auto-created in DB if MC# provided
      5. Every step logged to automation_logs
    """
    if not verify_internal_token(x_internal_token):
        raise HTTPException(403, "Invalid internal token.")

    steps = []
    started_at = datetime.utcnow()

    # Step 1 — Receptionist qualifies
    context = (
        f"Caller Name: {data.caller_name}\n"
        f"Caller Phone: {data.caller_phone}\n"
        f"MC#: {data.mc_number or 'unknown'}\n"
        f"Message: {data.message}"
    )
    receptionist_reply = await asyncio.to_thread(
        run_agent, "RECEPTIONIST.md", data.message, context
    )
    steps.append({"step": 1, "agent": "Receptionist", "result": receptionist_reply})

    await _log(
        db, agent="receptionist", action_type="workflow_inbound_qualify_step1",
        description=f"Qualified: {data.caller_name} ({data.caller_phone})",
        result="qualified", carrier_mc=data.mc_number,
    )

    # Step 2 — Create lead in DB if MC# provided
    lead_created = False
    if data.mc_number:
        existing = await db.execute(
            select(Carrier).where(Carrier.mc_number == data.mc_number)
        )
        if not existing.scalar_one_or_none():
            carrier = Carrier(
                mc_number=data.mc_number,
                name=data.caller_name,
                phone=data.caller_phone,
                status=CarrierStatus.LEAD,
                notes=f"Auto-created by inbound workflow on {started_at.date()}",
            )
            db.add(carrier)
            await db.commit()
            lead_created = True
            steps.append({"step": 2, "agent": "Brain", "result": f"Lead created for MC#{data.mc_number}"})

    # Step 3 — Megan drafts follow-up SMS
    sdr_context = (
        f"Carrier: {data.caller_name} | MC#{data.mc_number or 'unknown'}\n"
        f"Phone: {data.caller_phone}\n"
        f"They reached out with: {data.message}\n"
        f"Receptionist response: {receptionist_reply[:300]}"
    )
    sdr_prompt = (
        f"Draft a warm follow-up SMS to {data.caller_name} (MC#{data.mc_number or 'unknown'}) "
        f"who just inquired about Verlytax dispatch services. Keep it concise, friendly, and specific. "
        f"Reference that we spoke with them today."
    )
    megan_draft = await asyncio.to_thread(
        run_agent, "SDR_MEGAN.md", sdr_prompt, sdr_context
    )
    steps.append({"step": 3, "agent": "Megan SDR", "result": megan_draft})

    await _log(
        db, agent="megan_sdr", action_type="workflow_inbound_qualify_step3",
        description=f"Follow-up SMS drafted for {data.caller_name}",
        result="drafted", carrier_mc=data.mc_number,
    )

    # Step 4 — Nova sends the follow-up
    sms_sent = False
    if data.caller_phone:
        nova_sms(data.caller_phone, megan_draft)
        sms_sent = True
        steps.append({"step": 4, "agent": "Nova", "result": f"Follow-up SMS sent to {data.caller_phone}"})
        await _log(
            db, agent="nova", action_type="workflow_inbound_qualify_step4",
            description=f"Follow-up SMS sent to {data.caller_name} ({data.caller_phone})",
            result="sent", carrier_mc=data.mc_number,
        )

    # Alert Delta
    nova_alert_ceo(
        subject=f"New Inbound Lead — {data.caller_name}",
        body=(
            f"Inbound workflow complete.\n"
            f"Caller: {data.caller_name} | Phone: {data.caller_phone} | MC#: {data.mc_number or 'unknown'}\n"
            f"Lead created: {'Yes' if lead_created else 'Already exists'}\n"
            f"Follow-up SMS sent: {'Yes' if sms_sent else 'No phone'}\n\n"
            f"Receptionist reply:\n{receptionist_reply}"
        ),
    )

    return {
        "workflow": "inbound_qualify",
        "status": "complete",
        "lead_created": lead_created,
        "sms_sent": sms_sent,
        "steps": steps,
        "duration_ms": int((datetime.utcnow() - started_at).total_seconds() * 1000),
    }


# ── Pipeline 2: Outbound Blast — Brain pulls leads → SDR drafts → Nova sends ──

@router.post("/outbound-blast")
async def workflow_outbound_blast(
    data: OutboundBlastRequest,
    x_internal_token: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Outbound campaign pipeline:
      1. Brain pulls up to {limit} stale leads (no contact in 14 days)
      2. Megan drafts a personalized SMS for each
      3. Nova sends each SMS immediately
      4. All sends logged to automation_logs
      5. Delta gets a blast summary
    """
    if not verify_internal_token(x_internal_token):
        raise HTTPException(403, "Invalid internal token.")

    if data.limit > 50:
        raise HTTPException(400, "Max blast limit is 50 per run.")

    started_at = datetime.utcnow()
    cutoff = started_at - timedelta(days=14)

    # Pull stale leads with phone numbers
    result = await db.execute(
        select(Carrier).where(
            Carrier.status == CarrierStatus.LEAD,
            Carrier.phone.isnot(None),
            Carrier.is_blocked == False,
            Carrier.created_at < cutoff,
        ).limit(data.limit)
    )
    leads = result.scalars().all()

    if not leads:
        return {
            "workflow": "outbound_blast",
            "status": "no_leads",
            "message": "No stale leads with phone numbers found.",
            "sent": 0,
        }

    sent, failed = [], []

    for lead in leads:
        try:
            sdr_context = (
                f"Carrier: {lead.name} | MC#{lead.mc_number}\n"
                f"Phone: {lead.phone}\n"
                f"Lead since: {lead.created_at.strftime('%B %d, %Y')}\n"
                f"Notes: {lead.notes or 'none'}\n"
                f"Extra context: {data.context or 'none'}"
            )
            sdr_prompt = (
                f"Draft a short outbound SMS to {lead.name} (MC#{lead.mc_number}) "
                f"who has been a lead for {(started_at - lead.created_at).days} days with no conversion. "
                f"Re-engage them — be direct, specific, and close with a clear next step."
            )

            draft = await asyncio.to_thread(run_agent, "SDR_MEGAN.md", sdr_prompt, sdr_context)
            nova_sms(lead.phone, draft)

            await _log(
                db, agent="megan_sdr", action_type="workflow_outbound_blast",
                description=f"Outbound blast SMS sent to {lead.name} MC#{lead.mc_number}",
                result="sent", carrier_mc=lead.mc_number,
            )
            sent.append(f"{lead.name} MC#{lead.mc_number}")

        except Exception as e:
            failed.append(f"{lead.name} MC#{lead.mc_number} — {str(e)}")
            await _log(
                db, agent="megan_sdr", action_type="workflow_outbound_blast",
                description=f"Blast failed for {lead.name} MC#{lead.mc_number}: {str(e)}",
                result="error", carrier_mc=lead.mc_number,
            )

    nova_alert_ceo(
        subject=f"Outbound Blast Complete — {len(sent)}/{len(leads)} sent",
        body=(
            f"SDR: Megan\n"
            f"Sent ({len(sent)}): {', '.join(sent) or 'none'}\n"
            f"Failed ({len(failed)}): {', '.join(failed) or 'none'}"
        ),
    )

    return {
        "workflow": "outbound_blast",
        "status": "complete",
        "sdr": "Megan",
        "total_leads": len(leads),
        "sent": len(sent),
        "failed": len(failed),
        "sent_to": sent,
        "duration_ms": int((datetime.utcnow() - started_at).total_seconds() * 1000),
    }


# ── Pipeline 3: Manual Brain Scan Trigger ─────────────────────────────────────

@router.post("/run-brain-scan")
async def workflow_run_brain_scan(
    data: ManualTriggerRequest,
    x_internal_token: str = Header(...),
):
    """
    Manually trigger any Brain autonomous scan on-demand.
    scan_type: "overdue_loads" | "no_load_carriers" | "stale_leads" | "all"
    Requires INTERNAL_TOKEN header.
    """
    if not verify_internal_token(x_internal_token):
        raise HTTPException(403, "Invalid internal token.")

    valid = {"overdue_loads", "no_load_carriers", "stale_leads", "all"}
    if data.scan_type not in valid:
        raise HTTPException(400, f"scan_type must be one of: {', '.join(valid)}")

    # Import here to avoid circular imports
    from app.main import brain_autonomous_scan

    await brain_autonomous_scan()

    log_automation(
        agent="brain", action_type="manual_brain_scan",
        description=f"Manual scan triggered: {data.scan_type}",
        result="triggered",
    )

    return {
        "workflow": "manual_brain_scan",
        "scan_type": data.scan_type,
        "status": "complete",
        "triggered_at": datetime.utcnow().isoformat(),
    }


# ── Workflow Run History ───────────────────────────────────────────────────────

@router.get("/runs")
async def workflow_run_history(
    limit: int = 25,
    db: AsyncSession = Depends(get_db),
):
    """
    Returns recent workflow pipeline runs from the automation log.
    Filters to entries with action_type starting with 'workflow_' or 'manual_'.
    """
    result = await db.execute(
        select(AutomationLog)
        .where(
            AutomationLog.action_type.like("workflow_%")
            | AutomationLog.action_type.like("manual_%")
        )
        .order_by(AutomationLog.created_at.desc())
        .limit(limit)
    )
    runs = result.scalars().all()

    return {
        "total": len(runs),
        "runs": [
            {
                "id": r.id,
                "agent": r.agent,
                "action_type": r.action_type,
                "carrier_mc": r.carrier_mc,
                "description": r.description,
                "result": r.result,
                "escalated_to_delta": r.escalated_to_delta,
                "created_at": r.created_at,
            }
            for r in runs
        ],
    }
