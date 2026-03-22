"""
Verlytax OS v4 — Agent Dispatch Routes
Wire Receptionist and Megan SDR to live API endpoints.
All require INTERNAL_TOKEN. All actions logged to automation_logs.
"""

import asyncio
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db import get_db, Carrier, CarrierStatus, AutomationLog
from app.services import verify_internal_token, run_agent, nova_sms, nova_alert_ceo, retell_initiate_call

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class ReceptionistRequest(BaseModel):
    caller_name: str
    caller_phone: str
    message: str
    mc_number: Optional[str] = None     # If known from inbound call metadata

class SdrRequest(BaseModel):
    carrier_name: str
    mc_number: str
    phone: Optional[str] = None
    context: Optional[str] = None       # Lane info, truck type, previous contact, etc.

class NovaSdrRequest(BaseModel):
    carrier_name: str
    mc_number: str
    phone: str                          # Required — Nova actually sends the SMS
    sdr_agent: str = "megan"           # "megan" | "dan" — whose voice drafts the message
    context: Optional[str] = None

class VoiceCallRequest(BaseModel):
    agent: str                          # "erin" | "ava" | "zara"
    to_number: str                      # E.164 format: +1XXXXXXXXXX
    carrier_mc: Optional[str] = None
    carrier_name: Optional[str] = None
    metadata: Optional[dict] = None     # Extra context passed to Retell agent


# ── Helpers ───────────────────────────────────────────────────────────────────

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


# ── Receptionist ──────────────────────────────────────────────────────────────

@router.post("/receptionist")
async def receptionist_qualify(
    data: ReceptionistRequest,
    x_internal_token: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Run inbound lead through Receptionist agent.
    Qualifies the caller, returns Receptionist's response.
    If carrier MC# is provided and they pass basic screening, creates a lead in DB.
    """
    if not verify_internal_token(x_internal_token):
        raise HTTPException(403, "Invalid internal token.")

    context = (
        f"Caller Name: {data.caller_name}\n"
        f"Caller Phone: {data.caller_phone}\n"
        f"MC#: {data.mc_number or 'unknown'}\n"
        f"Message: {data.message}"
    )

    reply = await asyncio.to_thread(run_agent, "RECEPTIONIST.md", data.message, context)

    # If MC# provided and caller seems qualified, auto-create lead
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
                notes=f"Created by Receptionist agent on {datetime.utcnow().date()}",
            )
            db.add(carrier)
            await db.commit()
            lead_created = True

    await _log(
        db, agent="receptionist", action_type="inbound_qualification",
        description=f"Inbound from {data.caller_name} ({data.caller_phone}): {data.message[:100]}",
        result="lead_created" if lead_created else "responded",
        carrier_mc=data.mc_number,
    )

    return {
        "agent": "Receptionist",
        "reply": reply,
        "lead_created": lead_created,
        "mc_number": data.mc_number,
    }


# ── Megan SDR ─────────────────────────────────────────────────────────────────

@router.post("/sdr/megan")
async def sdr_megan(
    data: SdrRequest,
    x_internal_token: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Megan SDR drafts a personalized outbound SMS for carrier acquisition.
    Returns the drafted message — Delta or Brain sends it via Nova.
    """
    if not verify_internal_token(x_internal_token):
        raise HTTPException(403, "Invalid internal token.")

    context = (
        f"Target Carrier: {data.carrier_name} | MC#{data.mc_number}\n"
        f"Phone: {data.phone or 'unknown'}\n"
        f"Additional context: {data.context or 'none'}"
    )

    reply = await asyncio.to_thread(
        run_agent, "SDR_MEGAN.md",
        f"Draft an outbound SMS to carrier {data.carrier_name} (MC#{data.mc_number}) to introduce Verlytax services.",
        context,
    )

    await _log(
        db, agent="megan_sdr", action_type="outbound_sdr_draft",
        description=f"SDR draft for {data.carrier_name} MC#{data.mc_number}",
        result="drafted",
        carrier_mc=data.mc_number,
    )

    return {
        "agent": "Megan SDR",
        "carrier": data.carrier_name,
        "mc_number": data.mc_number,
        "drafted_sms": reply,
        "note": "Review and send via /webhooks or Nova SMS.",
    }


# ── Dan SDR ───────────────────────────────────────────────────────────────────

@router.post("/sdr/dan")
async def sdr_dan(
    data: SdrRequest,
    x_internal_token: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Dan SDR drafts an outbound SMS (B-voice variant — different tone from Megan).
    Returns the drafted message.
    """
    if not verify_internal_token(x_internal_token):
        raise HTTPException(403, "Invalid internal token.")

    context = (
        f"Target Carrier: {data.carrier_name} | MC#{data.mc_number}\n"
        f"Phone: {data.phone or 'unknown'}\n"
        f"Additional context: {data.context or 'none'}"
    )

    reply = await asyncio.to_thread(
        run_agent, "SDR_DAN.md",
        f"Draft an outbound SMS to carrier {data.carrier_name} (MC#{data.mc_number}) to introduce Verlytax services.",
        context,
    )

    await _log(
        db, agent="dan_sdr", action_type="outbound_sdr_draft",
        description=f"SDR draft for {data.carrier_name} MC#{data.mc_number}",
        result="drafted",
        carrier_mc=data.mc_number,
    )

    return {
        "agent": "Dan SDR",
        "carrier": data.carrier_name,
        "mc_number": data.mc_number,
        "drafted_sms": reply,
        "note": "Review and send via /webhooks or Nova SMS.",
    }


# ── Nova SDR Send ─────────────────────────────────────────────────────────────

@router.post("/sdr/nova")
async def sdr_nova(
    data: NovaSdrRequest,
    x_internal_token: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Nova sends an outbound SDR SMS directly to the carrier.
    Drafts via Megan or Dan's voice, then fires it via Nova SMS.
    Use this when you want the message delivered immediately — not just drafted.
    Requires INTERNAL_TOKEN.
    """
    if not verify_internal_token(x_internal_token):
        raise HTTPException(403, "Invalid internal token.")

    if data.sdr_agent not in ("megan", "dan"):
        raise HTTPException(400, "sdr_agent must be 'megan' or 'dan'.")

    prompt_file = "SDR_MEGAN.md" if data.sdr_agent == "megan" else "SDR_DAN.md"
    agent_name = "Megan SDR" if data.sdr_agent == "megan" else "Dan SDR"

    context = (
        f"Target Carrier: {data.carrier_name} | MC#{data.mc_number}\n"
        f"Phone: {data.phone}\n"
        f"Additional context: {data.context or 'none'}\n"
        f"Note: This message will be sent immediately via Nova SMS. Keep it concise and SMS-friendly."
    )

    drafted = await asyncio.to_thread(
        run_agent, prompt_file,
        f"Draft a cold outbound SMS to carrier {data.carrier_name} (MC#{data.mc_number}). "
        f"This will be sent immediately — keep it under 160 characters.",
        context,
    )

    # Nova sends it now
    await asyncio.to_thread(nova_sms, data.phone, drafted)

    await _log(
        db, agent=f"nova_sdr_{data.sdr_agent}", action_type="outbound_sdr_sent",
        description=f"Nova sent {agent_name} SMS to {data.carrier_name} MC#{data.mc_number} at {data.phone}",
        result="sent",
        carrier_mc=data.mc_number,
    )

    return {
        "agent": f"Nova (via {agent_name})",
        "carrier": data.carrier_name,
        "mc_number": data.mc_number,
        "phone": data.phone,
        "sent_sms": drafted,
        "status": "sent",
    }


# ── Voice Call (Retell) ────────────────────────────────────────────────────────

@router.post("/voice-call")
async def initiate_voice_call(
    data: VoiceCallRequest,
    x_internal_token: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Initiate a Retell outbound voice call for any Verlytax voice agent.
    All voice agents route through Retell — Erin (dispatch), Ava (qualification), Zara (support).
    Requires INTERNAL_TOKEN.
    """
    if not verify_internal_token(x_internal_token):
        raise HTTPException(403, "Invalid internal token.")

    if data.agent not in ("erin", "ava", "zara"):
        raise HTTPException(400, "agent must be 'erin', 'ava', or 'zara'.")

    metadata = {
        **(data.metadata or {}),
        "carrier_mc": data.carrier_mc or "",
        "caller_name": data.carrier_name or "",
        "caller_phone": data.to_number,
    }

    result = await retell_initiate_call(
        to_number=data.to_number,
        agent=data.agent,
        metadata=metadata,
    )

    if result["status"] == "error":
        raise HTTPException(502, f"Retell call failed: {result['reason']}")

    await _log(
        db,
        agent=data.agent,
        action_type="voice_call_initiated",
        description=f"Outbound call to {data.to_number} via {data.agent.title()} (Retell)",
        result="initiated",
        carrier_mc=data.carrier_mc,
    )

    return {
        "agent": data.agent,
        "call_id": result["call_id"],
        "to_number": data.to_number,
        "status": "initiated",
    }
