"""
Verlytax OS v4 — Webhook Endpoints
Stripe payment events | Twilio SMS replies | Retell voice callbacks
All webhooks are signature-verified.
"""

import os
import hmac
import hashlib
from fastapi import APIRouter, Request, HTTPException, Header
from fastapi.responses import JSONResponse

from app.services import nova_alert_ceo, nova_sms, erin_respond, verify_twilio_signature, recall_memories

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

    # If from CEO, treat as Delta command
    if from_number == CEO_PHONE:
        erin_reply = await asyncio.to_thread(
            erin_respond,
            body,
            "[Delta (CEO) is speaking directly. Follow escalation rules for CEO commands.]",
        )
    else:
        # Look up carrier MC by phone, pull Mya memories for context
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

        erin_reply = await asyncio.to_thread(
            erin_respond, body, None, memory_context or None
        )

    # Send Erin's response back via SMS
    await asyncio.to_thread(nova_sms, from_number, erin_reply[:1600])

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

    if call_event == "call_ended":
        # Try to link back to a support ticket via call_id
        ticket_id = metadata.get("ticket_id")
        ticket_number = metadata.get("ticket_number", "")

        if ticket_id or call_id:
            from app.db import AsyncSessionLocal, SupportTicket
            from sqlalchemy import select
            from datetime import datetime

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
                    # Store transcript and mark resolved if call was successful
                    ticket.voice_transcript = transcript[:4000] if transcript else None
                    ticket.updated_at = datetime.utcnow()

                    # If call analysis indicates resolution, close the ticket
                    call_successful = call_analysis.get("call_successful", False)
                    if call_successful:
                        ticket.status = "resolved"
                        ticket.resolved_at = datetime.utcnow()
                        ticket.resolution = f"Resolved via Retell voice call {call_id}. Transcript stored."
                    await session.commit()

                    nova_alert_ceo(
                        subject=f"Voice Call Ended — {ticket.ticket_number or ticket_number}",
                        body=(
                            f"Call ID: {call_id}\n"
                            f"Ticket: {ticket.ticket_number}\n"
                            f"Carrier: MC#{ticket.carrier_mc or 'unknown'}\n"
                            f"Outcome: {'Resolved' if call_successful else 'Needs follow-up'}\n"
                            f"Transcript preview:\n{(transcript or 'No transcript')[:400]}"
                        ),
                    )
                    from app.services import log_automation
                    log_automation(
                        agent="zara", action_type="voice_call_ended",
                        description=f"{ticket.ticket_number} voice call ended — {'resolved' if call_successful else 'needs follow-up'}",
                        result="resolved" if call_successful else "escalated",
                        carrier_mc=ticket.carrier_mc,
                    )
                    return {"status": "ticket_updated", "ticket_number": ticket.ticket_number, "call_id": call_id}

        # No ticket linked — generic CEO alert
        if transcript:
            nova_alert_ceo(
                subject=f"Unlinked Voice Call Ended — {call_id or 'unknown'}",
                body=f"Call ID: {call_id}\nTranscript preview:\n{transcript[:500]}",
            )

    return {"status": "received", "event": call_event}


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
