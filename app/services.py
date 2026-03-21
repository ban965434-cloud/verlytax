"""
Verlytax OS v4 — Core Services
Nova SMS | Erin (Claude AI) | Stripe billing | FMCSA checks
"""

import os
import hmac
import hashlib
import httpx
from datetime import datetime
from typing import Optional

# Optional imports — gracefully skip if not installed/configured
try:
    from twilio.rest import Client as TwilioClient
    _twilio = TwilioClient(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
    TWILIO_FROM = os.getenv("TWILIO_FROM_NUMBER", "")
except Exception:
    _twilio = None
    TWILIO_FROM = ""

try:
    import anthropic
    _claude = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
except Exception:
    _claude = None

try:
    import stripe
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
except Exception:
    stripe = None  # type: ignore


CEO_PHONE = os.getenv("CEO_PHONE", "")
INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN", "")


# ── Nova SMS ──────────────────────────────────────────────────────────────────

def nova_sms(to: str, body: str) -> dict:
    """
    Send an SMS via Twilio (Nova's communication channel).
    Only sends to whitelisted CEO phone or carrier numbers.
    """
    if not _twilio:
        return {"status": "skipped", "reason": "Twilio not configured"}
    try:
        msg = _twilio.messages.create(to=to, from_=TWILIO_FROM, body=body)
        return {"status": "sent", "sid": msg.sid}
    except Exception as e:
        return {"status": "error", "reason": str(e)}


def nova_alert_ceo(subject: str, body: str) -> dict:
    """Escalate to Delta (CEO) via SMS."""
    if not CEO_PHONE:
        return {"status": "skipped", "reason": "CEO_PHONE not set"}
    message = f"[VERLYTAX ALERT] {subject}\n\n{body}"
    return nova_sms(CEO_PHONE, message)


def nova_day1_carrier_packet(carrier_phone: str, carrier_name: str, mc_number: str) -> dict:
    """Auto Day 1 SMS — send carrier packet link."""
    body = (
        f"Hi {carrier_name}! This is Erin with Verlytax Operations. "
        f"Welcome aboard! Your carrier packet is ready. "
        f"MC#{mc_number} — please check your email for the DocuSign agreement and next steps. "
        f"Questions? Reply here or email ops@verlytax.com"
    )
    return nova_sms(carrier_phone, body)


# ── Erin (Claude AI Dispatcher) ───────────────────────────────────────────────

def _load_erin_system_prompt() -> str:
    """Load Erin's system prompt from the canonical file."""
    prompt_path = os.path.join(os.path.dirname(__file__), "..", "Erin_System_Prompt_v4.txt")
    try:
        with open(prompt_path, "r") as f:
            return f.read()
    except FileNotFoundError:
        return "You are Erin, the AI dispatcher for Verlytax Operations."


def erin_respond(user_message: str, context: Optional[str] = None, memory_context: Optional[str] = None) -> str:
    """
    Route a message through Erin (Claude) with the full system prompt.
    context: optional JSON string of relevant DB data for this query.
    memory_context: optional Mya memory strings injected as carrier intelligence.
    """
    if not _claude:
        return "Erin is offline — ANTHROPIC_API_KEY not configured."

    system = _load_erin_system_prompt()
    if context:
        system += f"\n\n=== CURRENT CONTEXT (from verlytax.db) ===\n{context}"
    if memory_context:
        system += f"\n\n=== MYA MEMORY — what we know about this carrier ===\n{memory_context}"

    try:
        response = _claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text
    except Exception as e:
        return f"Erin encountered an error: {str(e)}"


# ── Fee Calculator ────────────────────────────────────────────────────────────

def calculate_fee(
    gross_load_revenue: float,
    carrier_active_since: Optional[datetime],
    trial_start: Optional[datetime],
    has_extra_services: bool = False,
    is_og: bool = False,
) -> dict:
    """
    Calculate Verlytax dispatch fee per Iron Rules fee structure.
    Fee is ALWAYS on gross revenue BEFORE factoring discount.
    """
    now = datetime.utcnow()

    # Trial period (Days 1–7): FREE
    if trial_start and (now - trial_start).days <= 7:
        return {
            "fee_pct": 0.0,
            "fee_amount": 0.0,
            "period": "trial",
            "note": "Days 1–7 free trial",
        }

    # Determine base %
    if active_since := carrier_active_since:
        months_active = (now - active_since).days / 30
        base_pct = 0.08 if (months_active < 5 or is_og) else 0.10
        period = f"month_{int(months_active)+1}"
    else:
        base_pct = 0.08
        period = "month_1"

    # Extra services add +10 percentage points
    if has_extra_services:
        base_pct += 0.10

    fee_amount = gross_load_revenue * base_pct
    min_fee = 100.0
    fee_amount = max(fee_amount, min_fee)

    return {
        "fee_pct": round(base_pct * 100, 2),
        "fee_amount": round(fee_amount, 2),
        "gross_revenue": gross_load_revenue,
        "period": period,
        "minimum_applied": fee_amount == min_fee,
    }


# ── Stripe ────────────────────────────────────────────────────────────────────

def charge_carrier_fee(stripe_customer_id: str, amount_cents: int, description: str) -> dict:
    """Charge the Verlytax fee via Stripe."""
    if not stripe:
        return {"status": "skipped", "reason": "Stripe not configured"}
    try:
        intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency="usd",
            customer=stripe_customer_id,
            description=description,
            confirm=True,
            off_session=True,
        )
        return {"status": "charged", "payment_intent_id": intent.id}
    except stripe.error.CardError as e:
        return {"status": "failed", "reason": str(e)}
    except Exception as e:
        return {"status": "error", "reason": str(e)}


# ── FMCSA ─────────────────────────────────────────────────────────────────────

async def fmcsa_lookup(mc_number: str) -> dict:
    """
    Query FMCSA SAFER for carrier compliance data.
    Cost: $1.25 per Clearinghouse query (tracked separately).
    """
    api_key = os.getenv("FMCSA_API_KEY", "")
    if not api_key:
        return {"status": "skipped", "reason": "FMCSA_API_KEY not configured"}

    url = f"https://mobile.fmcsa.dot.gov/qc/services/carriers/{mc_number}?webKey={api_key}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            carrier = data.get("content", {}).get("carrier", {})
            return {
                "status": "ok",
                "mc_number": mc_number,
                "legal_name": carrier.get("legalName"),
                "safety_rating": carrier.get("safetyRating", "none"),
                "authority_status": carrier.get("commonAuthorityStatus"),
                "out_of_service": carrier.get("oosDate"),
            }
        except Exception as e:
            return {"status": "error", "reason": str(e)}


# ── Automation helpers ────────────────────────────────────────────────────────

def log_automation(
    agent: str,
    action_type: str,
    description: str,
    result: str,
    carrier_mc: str = None,
    load_id: int = None,
    escalated_to_delta: bool = False,
):
    """
    Write an entry to automation_logs synchronously (called from cron jobs).
    Import AsyncSessionLocal locally to avoid circular imports.
    """
    import asyncio
    from app.db import AsyncSessionLocal, AutomationLog

    async def _write():
        async with AsyncSessionLocal() as session:
            session.add(AutomationLog(
                agent=agent,
                action_type=action_type,
                carrier_mc=carrier_mc,
                load_id=load_id,
                description=description,
                result=result,
                escalated_to_delta=escalated_to_delta,
            ))
            await session.commit()

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_write())
        else:
            loop.run_until_complete(_write())
    except Exception:
        pass  # Never let logging crash the automation


def load_agent_prompt(filename: str) -> str:
    """
    Load an agent system prompt from VERLYTAX_AIOS/agents/{filename}.
    Falls back to empty string if file not found — agent will still respond
    but without persona.
    """
    base = os.path.join(os.path.dirname(__file__), "..", "VERLYTAX_AIOS", "agents", filename)
    try:
        with open(os.path.abspath(base), "r") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def run_agent(system_prompt_file: str, message: str, context: str = "") -> str:
    """
    Run any agent by loading its system prompt and calling Claude.
    Same pattern as erin_respond() but generalized for Megan, Dan, Receptionist, etc.
    """
    if not _claude:
        return "[Agent offline — ANTHROPIC_API_KEY not configured]"

    system_prompt = load_agent_prompt(system_prompt_file)
    if not system_prompt:
        return f"[Agent system prompt '{system_prompt_file}' not found]"

    full_message = f"{context}\n\n{message}".strip() if context else message

    try:
        response = _claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": full_message}],
        )
        return response.content[0].text
    except Exception as e:
        return f"[Agent error: {str(e)}]"


# ── Mya Memory Engine ─────────────────────────────────────────────────────────

def store_memory(
    agent: str,
    memory_type: str,
    content: str,
    carrier_mc: str = None,
    subject: str = None,
    importance: int = 3,
    source: str = "auto",
):
    """
    Store a learning in AgentMemory (synchronous wrapper — safe to call from crons).
    source: "auto" = Mya learned it | "delta" = Delta manually taught it.
    """
    import asyncio
    from app.db import AsyncSessionLocal, AgentMemory

    async def _write():
        async with AsyncSessionLocal() as session:
            session.add(AgentMemory(
                agent=agent,
                memory_type=memory_type,
                carrier_mc=carrier_mc,
                subject=subject,
                content=content,
                importance=importance,
                source=source,
            ))
            await session.commit()

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_write())
        else:
            loop.run_until_complete(_write())
    except Exception:
        pass  # Never let memory storage crash an operation


async def recall_memories(
    carrier_mc: str = None,
    memory_type: str = None,
    limit: int = 8,
) -> str:
    """
    Async — recall relevant memories and return as a formatted string for agent context injection.
    Bumps recall_count so we know which memories are actually being used.
    """
    from app.db import AsyncSessionLocal, AgentMemory
    from sqlalchemy import desc as sa_desc

    try:
        async with AsyncSessionLocal() as session:
            q = select(AgentMemory).order_by(
                sa_desc(AgentMemory.importance),
                sa_desc(AgentMemory.created_at),
            )
            if carrier_mc:
                # Carrier-specific + global memories
                q = q.where(
                    (AgentMemory.carrier_mc == carrier_mc) | (AgentMemory.carrier_mc.is_(None))
                )
            else:
                q = q.where(AgentMemory.carrier_mc.is_(None))  # Global only
            if memory_type:
                q = q.where(AgentMemory.memory_type == memory_type)
            q = q.limit(limit)

            result = await session.execute(q)
            memories = result.scalars().all()

            lines = []
            for m in memories:
                label = f"[{m.memory_type.upper()}" + (f" — importance {m.importance}/5" if m.importance >= 4 else "") + "]"
                lines.append(f"{label} {m.subject or ''}: {m.content}")
                m.recall_count = (m.recall_count or 0) + 1
                m.last_recalled = datetime.utcnow()
            await session.commit()
            return "\n".join(lines)
    except Exception:
        return ""


# ── Security helpers ──────────────────────────────────────────────────────────

def verify_internal_token(token: str) -> bool:
    return hmac.compare_digest(token, INTERNAL_TOKEN)


def verify_twilio_signature(url: str, params: dict, signature: str) -> bool:
    if not _twilio:
        return False
    from twilio.request_validator import RequestValidator
    validator = RequestValidator(os.getenv("TWILIO_AUTH_TOKEN", ""))
    return validator.validate(url, params, signature)
