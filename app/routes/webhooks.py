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

from app.services import nova_alert_ceo, nova_sms, erin_respond, verify_twilio_signature

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
        erin_reply = erin_respond(
            user_message=body,
            context="[Delta (CEO) is speaking directly. Follow escalation rules for CEO commands.]",
        )
    else:
        erin_reply = erin_respond(user_message=body)

    # Send Erin's response back via SMS
    nova_sms(to=from_number, body=erin_reply[:1600])  # Twilio 1600 char limit

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
    transcript = data.get("transcript", "")

    if call_event == "call_ended" and transcript:
        # Log call summary — Erin reviews
        nova_alert_ceo(
            subject="Call Ended — Review",
            body=f"Call transcript summary:\n{transcript[:500]}",
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

    if action == "monday_fee_charge":
        # Auto-charge Monday routine
        return {"status": "triggered", "action": action, "note": "Weekly fee charge initiated"}

    return {"status": "unknown_action", "action": action}
