"""
Verlytax OS v4 — Webhook Endpoints
Stripe payment events | Twilio SMS replies | Retell voice callbacks
All webhooks are signature-verified.
"""

import os
import hmac
import hashlib
import asyncio
from fastapi import APIRouter, Request, HTTPException, Header
from fastapi.responses import JSONResponse

from app.services import nova_alert_ceo, nova_sms, nova_respond, erin_respond, verify_twilio_signature, recall_memories, run_agent, log_automation, store_memory, RETELL_AGENT_IDS

router = APIRouter()

CEO_PHONE = os.getenv("CEO_PHONE", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")


# ── Stripe Webhooks ───────────────────────────────────────────────────────────

@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="stripe-signature"),
):
    """
    Handle Stripe payment events.
    - payment_intent.succeeded → mark fee collected
    - payment_intent.payment_failed → suspend carrier + alert Delta
    - customer.subscription.deleted → deactivate carrier
    """
    try:
        import stripe
        body = await request.body()
        event = stripe.Webhook.construct_event(body, stripe_signature, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        raise HTTPException(400, f"Stripe signature verification failed: {e}")

    event_type = event["type"]
    obj = event["data"]["object"]

    if event_type == "payment_intent.succeeded":
        nova_alert_ceo(
            subject="Fee Collected",
            body=f"Payment of ${obj['amount']/100:.2f} succeeded. Customer: {obj.get('customer')}",
        )
        return {"status": "processed", "event": event_type}

    if event_type == "payment_intent.payment_failed":
        customer_id = obj.get("customer")
        nova_alert_ceo(
            subject="PAYMENT FAILED — Action Required",
            body=f"Payment failed for customer {customer_id}. Amount: ${obj['amount']/100:.2f}. Carrier suspended.",
        )
        return {"status": "processed", "event": event_type}

    if event_type == "customer.subscription.deleted":
        nova_alert_ceo(
            subject="Subscription Cancelled",
            body=f"Customer {obj.get('customer')} subscription cancelled.",
        )
        return {"status": "processed", "event": event_type}

    return {"status": "ignored", "event": event_type}


# ── Twilio SMS Webhooks ───────────────────────────────────────────────────────

@router.post("/twilio/sms")
async def twilio_sms_reply(request: Request):
    """
    Handle inbound SMS replies from carriers.
    Routes message through Erin for response generation.
    """
    form = await request.form()
    signature = request.headers.get("X-Twilio-Signature", "")
    url = str(request.url)

    # Verify Twilio signature (security guard)
    if not verify_twilio_signature(url, dict(form), signature):
        raise HTTPException(403, "Invalid Twilio signature.")

    from_number = form.get("From", "")
    body = form.get("Body", "")

    # If from CEO — route to Nova (Delta's operator, not Erin)
    if from_number == CEO_PHONE:
        # Check for ACTIVATE CEO command
        cmd = body.strip().upper()
        if cmd == "ACTIVATE CEO":
            log_automation(
                agent="ceo_agent",
                action_type="activation_command",
                description="Delta sent ACTIVATE CEO — CEO Agent transitioning to active mode.",
                result="pending_activation",
            )
            store_memory(
                agent="ceo_agent",
                memory_type="activation_event",
                content="Delta issued ACTIVATE CEO command. CEO Agent mode transition initiated.",
                subject="CEO Agent Activation",
                importance=5,
                source="delta",
            )
            reply = (
                "CEO Agent activation received.\n\n"
                "Activation gate:\n"
                "- Shadow observations logged: see /nova/shadow-log\n"
                "- Training log: see /nova/training-log\n\n"
                "To complete activation, confirm readiness in the dashboard "
                "and toggle the CEO Agent rule in Brain. "
                "Nova will alert Delta when the gate is cleared."
            )
        else:
            reply = await asyncio.to_thread(
                nova_respond,
                body,
                "Inbound SMS from Delta (CEO). Execute commands or answer questions per Nova protocols.",
            )
            # CEO shadow: log every real Delta command as a training observation
            store_memory(
                agent="ceo_agent",
                memory_type="delta_command",
                content=f"Delta SMS: {body}\nNova response: {reply}",
                subject=f"Delta command: {body[:60]}",
                importance=4,
                source="delta",
            )
            log_automation(
                agent="nova",
                action_type="ceo_sms_command",
                description=f"CEO SMS: {body[:80]}",
                result=reply[:200],
            )
    else:
        # Carrier SMS — route to Erin; pull Mya memories for context
        carrier_mc = None
        memory_context = ""
        try:
            from app.db import AsyncSessionLocal, Carrier
            from sqlalchemy import select
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Carrier).where(Carrier.phone == from_number)
                )
                carrier = result.scalar_one_or_none()
                if carrier:
                    carrier_mc = carrier.mc_number
            if carrier_mc:
                memory_context = await recall_memories(carrier_mc=carrier_mc, limit=6)
        except Exception:
            pass  # Memory lookup failure should never block Erin

        reply = await asyncio.to_thread(
            erin_respond, body, None, memory_context or None
        )

    # Send response back via SMS
    await asyncio.to_thread(nova_sms, from_number, reply[:1600])

    # TwiML response (empty — we already sent via API)
    return JSONResponse(
        content={"status": "replied", "to": from_number},
        headers={"Content-Type": "application/json"},
    )


# ── Retell Voice Webhooks ─────────────────────────────────────────────────────

@router.post("/retell")
async def retell_callback(request: Request):
    """
    Handle Retell AI voice call events.
    Retell runs the voice interface — Erin logic handles dispatch decisions.
    """
    # Verify Retell signature
    retell_api_key = os.getenv("RETELL_API_KEY", "")
    signature = request.headers.get("x-retell-signature", "")
    body = await request.body()

    if retell_api_key:
        expected = hmac.new(retell_api_key.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(403, "Invalid Retell signature.")

    data = await request.json() if body else {}
    call_event = data.get("event")
    call_id = data.get("call_id") or data.get("id")
    transcript = data.get("transcript", "")
    call_analysis = data.get("call_analysis", {})
    metadata = data.get("metadata", {})
    call_successful = call_analysis.get("call_successful", False)

    # Identify which voice agent handled this call
    incoming_agent_id = data.get("agent_id", "")
    verlytax_agent = metadata.get("verlytax_agent", "")  # set by retell_initiate_call()

    # Resolve agent name from env var map if not in metadata
    if not verlytax_agent:
        for name, env_key in RETELL_AGENT_IDS.items():
            if incoming_agent_id and incoming_agent_id == os.getenv(env_key, ""):
                verlytax_agent = name
                break

    from app.db import AsyncSessionLocal, SupportTicket, Carrier, CarrierStatus
    from sqlalchemy import select
    from datetime import datetime

    # ── Zara — support ticket call ─────────────────────────────────────────────
    if verlytax_agent == "zara" or metadata.get("ticket_id"):
        ticket_id = metadata.get("ticket_id")
        async with AsyncSessionLocal() as session:
            ticket = None
            if ticket_id:
                ticket = await session.get(SupportTicket, int(ticket_id))
            if not ticket and call_id:
                result = await session.execute(
                    select(SupportTicket).where(SupportTicket.voice_call_id == call_id)
                )
                ticket = result.scalar_one_or_none()

            if ticket:
                ticket.voice_transcript = transcript[:4000] if transcript else None
                ticket.updated_at = datetime.utcnow()
                if call_successful:
                    ticket.status = "resolved"
                    ticket.resolved_at = datetime.utcnow()
                    ticket.resolution = f"Resolved via Retell voice call. Call ID: {call_id}"
                await session.commit()

                nova_alert_ceo(
                    subject=f"Zara Voice Call Ended — {ticket.ticket_number}",
                    body=(
                        f"Call ID: {call_id}\n"
                        f"Ticket: {ticket.ticket_number} | Carrier: MC#{ticket.carrier_mc or 'unknown'}\n"
                        f"Outcome: {'Resolved ✓' if call_successful else 'Needs follow-up'}\n"
                        f"Transcript preview:\n{(transcript or 'No transcript')[:400]}"
                    ),
                )
                log_automation(
                    agent="zara", action_type="voice_call_ended",
                    description=f"{ticket.ticket_number} — {'resolved' if call_successful else 'needs follow-up'}",
                    result="resolved" if call_successful else "escalated",
                    carrier_mc=ticket.carrier_mc,
                )
                return {"status": "ticket_updated", "ticket_number": ticket.ticket_number, "agent": "zara"}

    # ── Ava — inbound new lead qualification call ───────────────────────────────
    elif verlytax_agent == "ava":
        caller_name = metadata.get("caller_name", "Unknown")
        caller_phone = metadata.get("caller_phone") or data.get("from_number", "")
        caller_mc = metadata.get("mc_number")

        if call_event == "call_ended" and transcript:
            # Run Ava agent to analyze transcript and determine qualification
            import asyncio
            context = (
                f"Caller: {caller_name} | Phone: {caller_phone} | MC#: {caller_mc or 'unknown'}\n"
                f"Call transcript:\n{transcript[:2000]}"
            )
            qualification = await asyncio.to_thread(
                run_agent, "RECEPTIONIST.md",
                "Based on this call transcript, did this carrier qualify? Summarize: yes/no and why.",
                context,
            )

            # Auto-create lead if MC# was mentioned
            if caller_mc:
                async with AsyncSessionLocal() as session:
                    existing = await session.execute(
                        select(Carrier).where(Carrier.mc_number == caller_mc)
                    )
                    if not existing.scalar_one_or_none():
                        carrier = Carrier(
                            mc_number=caller_mc,
                            name=caller_name,
                            phone=caller_phone,
                            status=CarrierStatus.LEAD,
                            notes=f"Inbound voice call via Retell/Ava. Call ID: {call_id}",
                        )
                        session.add(carrier)
                        await session.commit()

            nova_alert_ceo(
                subject=f"Ava Inbound Call — {caller_name}",
                body=(
                    f"Caller: {caller_name} | Phone: {caller_phone} | MC#: {caller_mc or 'unknown'}\n"
                    f"Call ID: {call_id}\n\n"
                    f"Ava's assessment:\n{qualification}\n\n"
                    f"Transcript preview:\n{transcript[:400]}"
                ),
            )
            log_automation(
                agent="ava", action_type="inbound_voice_call",
                description=f"Inbound call from {caller_name} ({caller_phone}) — {call_id}",
                result="qualified" if call_successful else "reviewed",
                carrier_mc=caller_mc,
            )
        return {"status": "processed", "agent": "ava", "call_id": call_id}

    # ── Erin — inbound carrier dispatch call ───────────────────────────────────
    elif verlytax_agent == "erin":
        carrier_mc = metadata.get("carrier_mc")
        carrier_phone = data.get("from_number", "")

        if call_event == "call_ended" and transcript:
            # Erin reviews the transcript for anything requiring action
            import asyncio
            context = (
                f"Carrier MC#: {carrier_mc or 'unknown'} | Phone: {carrier_phone}\n"
                f"Call transcript:\n{transcript[:2000]}"
            )
            erin_summary = await asyncio.to_thread(
                erin_respond,
                "Review this call transcript. Identify any action items, commitments made, or issues requiring follow-up. Be specific.",
                context,
            )

            nova_alert_ceo(
                subject=f"Erin Inbound Call Ended — MC#{carrier_mc or 'unknown'}",
                body=(
                    f"Carrier: MC#{carrier_mc or 'unknown'} | Phone: {carrier_phone}\n"
                    f"Call ID: {call_id}\n\n"
                    f"Erin's action items:\n{erin_summary}\n\n"
                    f"Transcript preview:\n{transcript[:400]}"
                ),
            )
            log_automation(
                agent="erin", action_type="inbound_voice_call",
                description=f"Inbound dispatch call from MC#{carrier_mc or 'unknown'} — {call_id}",
                result="reviewed",
                carrier_mc=carrier_mc,
            )
        return {"status": "processed", "agent": "erin", "call_id": call_id}

    # ── Unrouted call — log and alert Delta ────────────────────────────────────
    else:
        if call_event == "call_ended" and transcript:
            nova_alert_ceo(
                subject=f"Unrouted Voice Call Ended — {call_id or 'unknown'}",
                body=(
                    f"Agent ID: {incoming_agent_id}\n"
                    f"Call ID: {call_id}\n"
                    f"Transcript:\n{transcript[:500]}"
                ),
            )

    return {"status": "received", "event": call_event, "agent": verlytax_agent or "unknown"}


# ── Internal Webhook (Brain/automation triggers) ──────────────────────────────

@router.post("/internal")
async def internal_trigger(request: Request, x_internal_token: str = Header(None)):
    """
    Internal automation triggers (Brain scheduler, cron jobs, etc.).
    Requires INTERNAL_TOKEN header.
    """
    from app.services import verify_internal_token
    if not x_internal_token or not verify_internal_token(x_internal_token):
        raise HTTPException(403, "Unauthorized — invalid internal token.")

    data = await request.json()
    action = data.get("action")

    if action == "annual_clearinghouse_requery":
        # Brain Scheduler: annual re-query on all active carriers
        nova_alert_ceo(
            subject="Annual Clearinghouse Re-query Triggered",
            body="Brain Scheduler has initiated the annual FMCSA Clearinghouse re-query for all active carriers.",
        )
        return {"status": "triggered", "action": action}

    if action == "friday_fee_charge":
        # Auto-charge Friday routine
        from app.main import friday_fee_charge
        import asyncio
        asyncio.create_task(friday_fee_charge())
        return {"status": "triggered", "action": action, "note": "Friday fee charge initiated"}

    return {"status": "unknown_action", "action": action}
