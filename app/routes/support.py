"""
Verlytax OS v4 — Zara: Customer Support Department
Carrier support tickets, billing questions, load issues, account inquiries.
Zara triages, responds, resolves, or escalates — every ticket gets handled.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func

from app.db import get_db, SupportTicket, Carrier, AutomationLog
from app.services import verify_internal_token, run_agent, nova_sms, nova_alert_ceo, log_automation

router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────────────────

class TicketCreate(BaseModel):
    carrier_mc: Optional[str] = None
    phone: Optional[str] = None
    category: str           # billing | load_issue | compliance | account | general
    subject: str
    description: str
    priority: str = "normal"  # low | normal | high | urgent

class TicketRespond(BaseModel):
    send_sms: bool = True   # if True + phone on file, Nova sends SMS to carrier

class TicketResolve(BaseModel):
    resolution: str

class TicketEscalate(BaseModel):
    escalate_to: str        # "erin" | "delta"
    reason: str

class ZaraChatRequest(BaseModel):
    message: str
    carrier_mc: Optional[str] = None


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _next_ticket_number(db: AsyncSession) -> str:
    result = await db.execute(select(func.count()).select_from(SupportTicket))
    count = result.scalar() or 0
    return f"TKT-{(count + 1):04d}"


async def _auto_triage(ticket: SupportTicket, db: AsyncSession) -> str:
    """
    Zara auto-triages a new ticket: sets priority + assigned_to based on category/keywords.
    Returns the triage decision as a string.
    """
    description_lower = (ticket.description or "").lower()
    subject_lower = (ticket.subject or "").lower()
    text = description_lower + " " + subject_lower

    # Urgent: money mentions, Iron Rule words, legal, or threat to leave
    if any(w in text for w in ["suspend", "leaving", "cancel", "legal", "lawyer", "irs", "iron rule"]):
        ticket.priority = "urgent"
        ticket.assigned_to = "delta"
        return "urgent_delta"

    # High: billing disputes, payment failures
    if any(w in text for w in ["fee", "charge", "payment", "stripe", "overcharged", "dispute"]):
        ticket.priority = "high"
        ticket.assigned_to = "erin" if ticket.category == "billing" else "zara"
        return "high_billing"

    # High: load issues in transit
    if ticket.category == "load_issue" and any(w in text for w in ["pickup", "delivery", "broker", "load", "bol"]):
        ticket.priority = "high"
        ticket.assigned_to = "erin"
        return "high_load"

    # Compliance questions → Cora-territory, but Zara handles first response
    if ticket.category == "compliance":
        ticket.priority = "normal"
        ticket.assigned_to = "zara"
        return "normal_compliance"

    # Default
    ticket.priority = ticket.priority or "normal"
    ticket.assigned_to = "zara"
    return "normal"


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/ticket")
async def create_ticket(
    data: TicketCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new support ticket. Zara auto-triages immediately.
    If carrier has a phone on file, Zara sends an acknowledgment SMS.
    No token required — carriers (or internal) can create tickets.
    """
    valid_categories = {"billing", "load_issue", "compliance", "account", "general"}
    if data.category not in valid_categories:
        raise HTTPException(400, f"category must be one of: {', '.join(sorted(valid_categories))}")

    ticket_number = await _next_ticket_number(db)

    ticket = SupportTicket(
        ticket_number=ticket_number,
        carrier_mc=data.carrier_mc,
        phone=data.phone,
        category=data.category,
        subject=data.subject,
        description=data.description,
        priority=data.priority,
        status="open",
        assigned_to="zara",
    )

    # Auto-triage
    triage = await _auto_triage(ticket, db)
    db.add(ticket)
    await db.commit()

    # Look up carrier phone if not provided
    phone = data.phone
    if not phone and data.carrier_mc:
        carrier_result = await db.execute(
            select(Carrier).where(Carrier.mc_number == data.carrier_mc)
        )
        carrier = carrier_result.scalar_one_or_none()
        if carrier:
            phone = carrier.phone
            ticket.phone = phone

    # Acknowledgment SMS to carrier
    if phone:
        nova_sms(
            phone,
            f"Hi, this is Zara with Verlytax Support. We received your support request "
            f"({ticket_number}): \"{data.subject}\". "
            f"I'm on it and will follow up shortly. Reply here anytime."
        )
        await db.commit()

    # Alert Delta if urgent
    if ticket.priority == "urgent":
        nova_alert_ceo(
            subject=f"URGENT SUPPORT TICKET — {ticket_number}",
            body=(
                f"Ticket: {ticket_number}\n"
                f"Carrier: MC#{data.carrier_mc or 'unknown'}\n"
                f"Subject: {data.subject}\n"
                f"Category: {data.category}\n"
                f"Description: {data.description[:300]}"
            ),
        )

    log_automation(
        agent="zara", action_type="ticket_created",
        description=f"{ticket_number}: {data.subject[:80]}",
        result=triage, carrier_mc=data.carrier_mc,
        escalated_to_delta=(ticket.priority == "urgent"),
    )

    return {
        "ticket_number": ticket_number,
        "status": "open",
        "priority": ticket.priority,
        "assigned_to": ticket.assigned_to,
        "triage": triage,
        "ack_sms_sent": bool(phone),
    }


@router.get("/tickets")
async def list_tickets(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    carrier_mc: Optional[str] = None,
    assigned_to: Optional[str] = None,
    limit: int = 25,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """List support tickets with filters."""
    q = select(SupportTicket).order_by(
        desc(SupportTicket.created_at)
    )
    if status:
        q = q.where(SupportTicket.status == status)
    if priority:
        q = q.where(SupportTicket.priority == priority)
    if carrier_mc:
        q = q.where(SupportTicket.carrier_mc == carrier_mc)
    if assigned_to:
        q = q.where(SupportTicket.assigned_to == assigned_to)
    q = q.offset(offset).limit(limit)

    result = await db.execute(q)
    tickets = result.scalars().all()

    return {
        "total": len(tickets),
        "offset": offset,
        "tickets": [
            {
                "id": t.id,
                "ticket_number": t.ticket_number,
                "carrier_mc": t.carrier_mc,
                "category": t.category,
                "subject": t.subject,
                "status": t.status,
                "priority": t.priority,
                "assigned_to": t.assigned_to,
                "created_at": t.created_at,
                "resolved_at": t.resolved_at,
            }
            for t in tickets
        ],
    }


@router.get("/tickets/{ticket_id}")
async def get_ticket(ticket_id: int, db: AsyncSession = Depends(get_db)):
    """Full ticket detail including Zara's response and resolution."""
    ticket = await db.get(SupportTicket, ticket_id)
    if not ticket:
        raise HTTPException(404, f"Ticket #{ticket_id} not found.")
    return {
        "id": ticket.id,
        "ticket_number": ticket.ticket_number,
        "carrier_mc": ticket.carrier_mc,
        "phone": ticket.phone,
        "category": ticket.category,
        "subject": ticket.subject,
        "description": ticket.description,
        "status": ticket.status,
        "priority": ticket.priority,
        "assigned_to": ticket.assigned_to,
        "zara_response": ticket.zara_response,
        "resolution": ticket.resolution,
        "escalation_reason": ticket.escalation_reason,
        "created_at": ticket.created_at,
        "updated_at": ticket.updated_at,
        "resolved_at": ticket.resolved_at,
    }


@router.post("/tickets/{ticket_id}/respond")
async def respond_to_ticket(
    ticket_id: int,
    data: TicketRespond,
    x_internal_token: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Zara generates a response to the ticket and optionally sends it via SMS.
    Requires INTERNAL_TOKEN.
    """
    if not verify_internal_token(x_internal_token):
        raise HTTPException(403, "Invalid internal token.")

    ticket = await db.get(SupportTicket, ticket_id)
    if not ticket:
        raise HTTPException(404, f"Ticket #{ticket_id} not found.")
    if ticket.status in ("resolved", "escalated"):
        raise HTTPException(400, f"Ticket is already {ticket.status}.")

    # Zara drafts a response
    context = (
        f"Support Ticket: {ticket.ticket_number}\n"
        f"Carrier MC#: {ticket.carrier_mc or 'unknown'}\n"
        f"Category: {ticket.category}\n"
        f"Subject: {ticket.subject}\n"
        f"Description: {ticket.description}\n"
        f"Priority: {ticket.priority}"
    )
    prompt = f"Draft a professional, helpful SMS response to this carrier support ticket. Be specific, warm, and give a clear next step with a deadline."
    response = await asyncio.to_thread(run_agent, "ZARA.md", prompt, context)

    ticket.zara_response = response
    ticket.status = "in_progress"
    ticket.updated_at = datetime.utcnow()
    await db.commit()

    sms_sent = False
    if data.send_sms and ticket.phone:
        nova_sms(ticket.phone, response[:1600])
        sms_sent = True

    log_automation(
        agent="zara", action_type="ticket_responded",
        description=f"{ticket.ticket_number}: response drafted + {'sent' if sms_sent else 'not sent'}",
        result="responded", carrier_mc=ticket.carrier_mc,
    )

    return {
        "ticket_number": ticket.ticket_number,
        "response": response,
        "sms_sent": sms_sent,
        "status": ticket.status,
    }


@router.post("/tickets/{ticket_id}/resolve")
async def resolve_ticket(
    ticket_id: int,
    data: TicketResolve,
    x_internal_token: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """Mark a ticket resolved. Requires INTERNAL_TOKEN."""
    if not verify_internal_token(x_internal_token):
        raise HTTPException(403, "Invalid internal token.")

    ticket = await db.get(SupportTicket, ticket_id)
    if not ticket:
        raise HTTPException(404, f"Ticket #{ticket_id} not found.")

    ticket.status = "resolved"
    ticket.resolution = data.resolution
    ticket.resolved_at = datetime.utcnow()
    ticket.updated_at = datetime.utcnow()
    await db.commit()

    # Notify carrier
    if ticket.phone:
        nova_sms(
            ticket.phone,
            f"Hi, this is Zara with Verlytax Support. Your ticket {ticket.ticket_number} has been resolved. "
            f"{data.resolution[:200]} "
            f"Any other questions — just reply here anytime."
        )

    log_automation(
        agent="zara", action_type="ticket_resolved",
        description=f"{ticket.ticket_number} resolved: {data.resolution[:80]}",
        result="resolved", carrier_mc=ticket.carrier_mc,
    )

    return {"ticket_number": ticket.ticket_number, "status": "resolved"}


@router.post("/tickets/{ticket_id}/escalate")
async def escalate_ticket(
    ticket_id: int,
    data: TicketEscalate,
    x_internal_token: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Escalate a ticket to Erin or Delta. Requires INTERNAL_TOKEN.
    Always alerts Delta via Nova regardless of who it's escalated to.
    """
    if not verify_internal_token(x_internal_token):
        raise HTTPException(403, "Invalid internal token.")

    if data.escalate_to not in ("erin", "delta"):
        raise HTTPException(400, "escalate_to must be 'erin' or 'delta'.")

    ticket = await db.get(SupportTicket, ticket_id)
    if not ticket:
        raise HTTPException(404, f"Ticket #{ticket_id} not found.")

    ticket.status = "escalated"
    ticket.assigned_to = data.escalate_to
    ticket.escalation_reason = data.reason
    ticket.updated_at = datetime.utcnow()
    await db.commit()

    nova_alert_ceo(
        subject=f"Ticket Escalated to {data.escalate_to.title()} — {ticket.ticket_number}",
        body=(
            f"Ticket: {ticket.ticket_number}\n"
            f"Carrier: MC#{ticket.carrier_mc or 'unknown'}\n"
            f"Subject: {ticket.subject}\n"
            f"Escalation reason: {data.reason}\n"
            f"Category: {ticket.category} | Priority: {ticket.priority}"
        ),
    )

    log_automation(
        agent="zara", action_type="ticket_escalated",
        description=f"{ticket.ticket_number} escalated to {data.escalate_to}: {data.reason[:80]}",
        result="escalated", carrier_mc=ticket.carrier_mc, escalated_to_delta=True,
    )

    return {
        "ticket_number": ticket.ticket_number,
        "status": "escalated",
        "assigned_to": data.escalate_to,
    }


@router.post("/chat")
async def zara_chat(req: ZaraChatRequest):
    """
    Live chat with Zara — Customer Support Specialist.
    No token required. Same pattern as /erin/chat.
    """
    context = f"Carrier MC#: {req.carrier_mc}" if req.carrier_mc else ""
    reply = await asyncio.to_thread(run_agent, "ZARA.md", req.message, context)
    return {"reply": reply, "agent": "Zara"}


@router.get("/stats")
async def support_stats(db: AsyncSession = Depends(get_db)):
    """Ticket stats: open count, by category, by status, avg resolution time."""
    result = await db.execute(select(SupportTicket))
    tickets = result.scalars().all()

    by_status = {}
    by_category = {}
    resolution_times = []

    for t in tickets:
        by_status[t.status] = by_status.get(t.status, 0) + 1
        by_category[t.category] = by_category.get(t.category, 0) + 1
        if t.resolved_at and t.created_at:
            hours = (t.resolved_at - t.created_at).total_seconds() / 3600
            resolution_times.append(hours)

    avg_resolution_hours = (
        round(sum(resolution_times) / len(resolution_times), 1)
        if resolution_times else None
    )

    return {
        "total": len(tickets),
        "open": by_status.get("open", 0),
        "in_progress": by_status.get("in_progress", 0),
        "resolved": by_status.get("resolved", 0),
        "escalated": by_status.get("escalated", 0),
        "by_category": by_category,
        "avg_resolution_hours": avg_resolution_hours,
    }
