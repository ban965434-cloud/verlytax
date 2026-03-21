"""
Verlytax OS v4 — FastAPI Application Entry Point
"You drive. We handle the rest."
"""

import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db import init_db, AsyncSessionLocal, Carrier, Load, CarrierStatus, LoadStatus, AutomationRule, AutomationLog
from app.routes import onboarding, billing, escalation, webhooks, carriers, brain, agents, workflows
from app.services import nova_alert_ceo, nova_sms, charge_carrier_fee, calculate_fee, erin_respond, fmcsa_lookup, log_automation

from sqlalchemy import select
from datetime import datetime


async def check_trial_touchpoints():
    """
    Daily job — sends the right Nova SMS based on how many days since trial started.
    Day 3: mid-trial check-in
    Day 7: convert offer (trial ends today)
    Day 14: win-back attempt 1 (didn't convert)
    Day 30: win-back attempt 2 + mark inactive
    """
    from app.services import nova_sms
    now = datetime.utcnow()

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Carrier).where(
                Carrier.trial_start_date.isnot(None),
                Carrier.is_blocked == False,
                Carrier.status.in_([CarrierStatus.TRIAL, CarrierStatus.CHURNED]),
            )
        )
        carriers = result.scalars().all()

    for carrier in carriers:
        days = (now - carrier.trial_start_date).days

        async with AsyncSessionLocal() as session:
            c = await session.get(Carrier, carrier.id)
            if not c:
                continue

            if days >= 3 and not c.sms_day3_sent and c.status == CarrierStatus.TRIAL:
                nova_sms(
                    c.phone,
                    f"Hi {c.name.split()[0]}, this is Erin with Verlytax Operations. "
                    f"You're 3 days into your free trial — how's everything going? "
                    f"Any questions on loads or routes, reply here anytime. "
                    f"We're working for you 24/7."
                )
                c.sms_day3_sent = True
                await session.commit()

            elif days >= 7 and not c.sms_day7_sent and c.status == CarrierStatus.TRIAL:
                async with AsyncSessionLocal() as load_session:
                    loads_result = await load_session.execute(
                        select(Load).where(Load.carrier_mc == c.mc_number)
                    )
                    load_count = len(loads_result.scalars().all())

                nova_sms(
                    c.phone,
                    f"Hi {c.name.split()[0]}, this is Erin with Verlytax. "
                    f"Your 7-day free trial wraps up today — you ran {load_count} load(s) with us. "
                    f"Ready to go active? Reply YES and I'll get your account set up. "
                    f"Rate stays at 8%, you get paid every Friday. No surprises."
                )
                c.sms_day7_sent = True
                await session.commit()

            elif days >= 14 and not c.sms_day14_sent and c.status == CarrierStatus.TRIAL:
                nova_sms(
                    c.phone,
                    f"Hi {c.name.split()[0]}, Erin here with Verlytax. "
                    f"I noticed your trial ended and didn't want to lose you. "
                    f"We still have your account ready — 8% rate, paid every Friday, no Florida loads. "
                    f"Reply YES to activate or call us anytime. "
                    f"Your truck deserves better miles."
                )
                c.sms_day14_sent = True
                await session.commit()

            elif days >= 30 and not c.sms_day30_sent:
                nova_sms(
                    c.phone,
                    f"Hi {c.name.split()[0]}, this is Erin with Verlytax — last check-in. "
                    f"We'd love to have you on the team. "
                    f"If the timing wasn't right before, we get it. "
                    f"Reply anytime and we'll pick up right where we left off. "
                    f"You drive. We handle the rest."
                )
                c.sms_day30_sent = True
                if c.status == CarrierStatus.TRIAL:
                    c.status = CarrierStatus.CHURNED
                await session.commit()
                nova_alert_ceo(
                    subject=f"Trial Expired — MC#{c.mc_number}",
                    body=f"{c.name} (MC#{c.mc_number}) did not convert after 30 days. Marked inactive.",
                )


async def friday_fee_charge():
    """Auto-charge all active carriers their weekly Verlytax fee every Friday."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Carrier).where(
                Carrier.status == CarrierStatus.ACTIVE,
                Carrier.stripe_customer_id.isnot(None),
                Carrier.is_blocked == False,
            )
        )
        carriers = result.scalars().all()

    charged, failed, skipped = [], [], []

    for carrier in carriers:
        # Sum unpaid load fees for this carrier
        async with AsyncSessionLocal() as session:
            loads_result = await session.execute(
                select(Load).where(
                    Load.carrier_mc == carrier.mc_number,
                    Load.fee_collected == False,
                    Load.status == LoadStatus.DELIVERED,
                )
            )
            pending_loads = loads_result.scalars().all()

        if not pending_loads:
            skipped.append(carrier.name)
            continue

        total_gross = sum(l.rate_total or 0 for l in pending_loads)
        fee_info = calculate_fee(
            gross_load_revenue=total_gross,
            carrier_active_since=carrier.active_since,
            trial_start=carrier.trial_start_date,
            is_og=carrier.is_og,
        )
        fee_cents = int(fee_info["fee_amount"] * 100)

        result = charge_carrier_fee(
            stripe_customer_id=carrier.stripe_customer_id,
            amount_cents=fee_cents,
            description=f"Verlytax weekly dispatch fee — {carrier.name} MC#{carrier.mc_number}",
        )

        if result["status"] == "charged":
            # Mark loads as fee collected
            async with AsyncSessionLocal() as session:
                for load in pending_loads:
                    load_obj = await session.get(Load, load.id)
                    if load_obj:
                        load_obj.fee_collected = True
                        load_obj.invoice_paid_at = datetime.utcnow()
                await session.commit()
            charged.append(f"{carrier.name} ${fee_info['fee_amount']:.2f}")
        else:
            # Suspend carrier on failed payment
            async with AsyncSessionLocal() as session:
                carrier_obj = await session.get(Carrier, carrier.id)
                if carrier_obj:
                    carrier_obj.status = CarrierStatus.SUSPENDED
                    await session.commit()
            failed.append(f"{carrier.name} — {result.get('reason', 'unknown')}")

    summary = (
        f"Friday fee run complete.\n"
        f"Charged ({len(charged)}): {', '.join(charged) or 'none'}\n"
        f"Failed/Suspended ({len(failed)}): {', '.join(failed) or 'none'}\n"
        f"Skipped/no loads ({len(skipped)}): {len(skipped)}"
    )
    nova_alert_ceo(subject="Friday Fee Charge Complete", body=summary)


async def _rule_enabled(rule_key: str) -> bool:
    """Check if an automation rule is enabled before running it."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AutomationRule).where(AutomationRule.rule_key == rule_key)
        )
        rule = result.scalar_one_or_none()
        return rule.enabled if rule else True  # Default to enabled if rule not seeded yet


async def coi_expiry_check():
    """
    Daily — alert Delta and SMS carriers whose COI expires within 30 days.
    Rule key: coi_expiry_check
    """
    if not await _rule_enabled("coi_expiry_check"):
        return

    from datetime import timedelta
    now = datetime.utcnow()
    warn_before = now + timedelta(days=30)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Carrier).where(
                Carrier.coi_expiry.isnot(None),
                Carrier.coi_expiry <= warn_before,
                Carrier.coi_expiry >= now,
                Carrier.status.in_([CarrierStatus.ACTIVE, CarrierStatus.TRIAL]),
                Carrier.is_blocked == False,
            )
        )
        expiring = result.scalars().all()

    if not expiring:
        return

    summary_lines = []
    for carrier in expiring:
        days_left = (carrier.coi_expiry - now).days
        msg = (
            f"Hi {carrier.name.split()[0]}, this is Erin with Verlytax Operations. "
            f"Your Certificate of Insurance expires on {carrier.coi_expiry.strftime('%B %d, %Y')} "
            f"({days_left} days). Please send your updated COI to ops@verlytax.com "
            f"by {(carrier.coi_expiry - timedelta(days=7)).strftime('%B %d')} to avoid a dispatch hold."
        )
        if carrier.phone:
            nova_sms(carrier.phone, msg)
        summary_lines.append(f"MC#{carrier.mc_number} {carrier.name} — expires {carrier.coi_expiry.strftime('%m/%d/%Y')}")
        log_automation(
            agent="brain", action_type="coi_expiry_sms",
            description=f"COI expires in {days_left} days",
            result="sent", carrier_mc=carrier.mc_number,
        )

    nova_alert_ceo(
        subject=f"COI Expiry Alert — {len(expiring)} carrier(s)",
        body="Carriers with COI expiring within 30 days:\n" + "\n".join(summary_lines),
    )


async def testimonial_sms():
    """
    Daily — send feedback/testimonial SMS at Day 30 and Day 60 of active status.
    Rule key: testimonial_sms
    """
    if not await _rule_enabled("testimonial_sms"):
        return

    now = datetime.utcnow()

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Carrier).where(
                Carrier.active_since.isnot(None),
                Carrier.status == CarrierStatus.ACTIVE,
                Carrier.is_blocked == False,
            )
        )
        active_carriers = result.scalars().all()

    for carrier in active_carriers:
        days_active = (now - carrier.active_since).days

        async with AsyncSessionLocal() as session:
            c = await session.get(Carrier, carrier.id)
            if not c:
                continue

            if days_active >= 30 and not c.sms_active_day30_sent:
                nova_sms(
                    c.phone,
                    f"Hi {c.name.split()[0]}, this is Erin with Verlytax. "
                    f"You've been with us a month — how are we doing? "
                    f"Any feedback helps us get better. Just reply here anytime."
                )
                c.sms_active_day30_sent = True
                await session.commit()
                log_automation(
                    agent="brain", action_type="testimonial_sms_day30",
                    description="30-day feedback SMS sent", result="sent",
                    carrier_mc=c.mc_number,
                )

            elif days_active >= 60 and not c.sms_active_day60_sent:
                nova_sms(
                    c.phone,
                    f"Hi {c.name.split()[0]}, Erin here. 60 days strong with Verlytax — "
                    f"that means a lot to us. If we've earned it, a quick Google review "
                    f"goes a long way. Reply and I'll send you the link. "
                    f"Either way — thank you for trusting us with your truck."
                )
                c.sms_active_day60_sent = True
                await session.commit()
                log_automation(
                    agent="brain", action_type="testimonial_sms_day60",
                    description="60-day review ask SMS sent", result="sent",
                    carrier_mc=c.mc_number,
                )


async def annual_fmcsa_recheck():
    """
    Yearly (Jan 1) — re-check FMCSA Clearinghouse for all active carriers.
    Suspend + alert Delta on any failure.
    Rule key: annual_fmcsa_recheck
    """
    if not await _rule_enabled("annual_fmcsa_recheck"):
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Carrier).where(
                Carrier.status == CarrierStatus.ACTIVE,
                Carrier.is_blocked == False,
            )
        )
        active_carriers = result.scalars().all()

    failed = []
    for carrier in active_carriers:
        try:
            fmcsa_data = await fmcsa_lookup(carrier.mc_number)
            safety = (fmcsa_data.get("safety_rating") or "").lower()
            out_of_service = fmcsa_data.get("out_of_service", False)

            if safety in ("unsatisfactory", "conditional") or out_of_service:
                async with AsyncSessionLocal() as session:
                    c = await session.get(Carrier, carrier.id)
                    if c:
                        c.status = CarrierStatus.SUSPENDED
                        c.safety_rating = safety or c.safety_rating
                        await session.commit()
                failed.append(f"MC#{carrier.mc_number} {carrier.name} — rating: {safety}, OOS: {out_of_service}")
                log_automation(
                    agent="brain", action_type="annual_fmcsa_recheck",
                    description=f"FAILED — safety: {safety}, OOS: {out_of_service}",
                    result="suspended", carrier_mc=carrier.mc_number, escalated_to_delta=True,
                )
            else:
                log_automation(
                    agent="brain", action_type="annual_fmcsa_recheck",
                    description=f"PASSED — safety: {safety}",
                    result="passed", carrier_mc=carrier.mc_number,
                )
        except Exception as e:
            log_automation(
                agent="brain", action_type="annual_fmcsa_recheck",
                description=f"Error: {str(e)}", result="error",
                carrier_mc=carrier.mc_number,
            )

    if failed:
        nova_alert_ceo(
            subject=f"Annual FMCSA Re-check — {len(failed)} FAILED",
            body="Carriers suspended due to FMCSA failure:\n" + "\n".join(failed),
        )
    nova_alert_ceo(
        subject="Annual FMCSA Re-check Complete",
        body=f"Checked {len(active_carriers)} active carriers. Failures: {len(failed)}.",
    )


async def brain_autonomous_scan():
    """
    Daily — Brain scans for overdue loads, no-load carriers, and stale leads.
    All governed by AutomationRule toggles.
    """
    now = datetime.utcnow()
    from datetime import timedelta

    # ── Overdue loads ──────────────────────────────────────────────────────────
    if await _rule_enabled("overdue_load_scan"):
        cutoff = now - timedelta(hours=24)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Load).where(
                    Load.status == LoadStatus.IN_TRANSIT,
                    Load.delivery_date.isnot(None),
                    Load.delivery_date < cutoff,
                )
            )
            overdue = result.scalars().all()

        for load in overdue:
            carrier_result = await session.execute(
                select(Carrier).where(Carrier.mc_number == load.carrier_mc)
            ) if False else None  # avoid stale session — use fresh session below
            async with AsyncSessionLocal() as session:
                carrier = (await session.execute(
                    select(Carrier).where(Carrier.mc_number == load.carrier_mc)
                )).scalar_one_or_none()

            if carrier and carrier.phone:
                nova_sms(
                    carrier.phone,
                    f"Hi {carrier.name.split()[0]}, Erin with Verlytax. "
                    f"Load #{load.id} was due {load.delivery_date.strftime('%B %d')} — "
                    f"can you confirm delivery status? Reply here or call ops@verlytax.com."
                )
            nova_alert_ceo(
                subject=f"OVERDUE LOAD #{load.id} — MC#{load.carrier_mc}",
                body=f"Load #{load.id} for {load.carrier_mc} was due {load.delivery_date}. Still in_transit.",
            )
            log_automation(
                agent="brain", action_type="overdue_load_alert",
                description=f"Load #{load.id} overdue by 24h+",
                result="alerted", carrier_mc=load.carrier_mc, escalated_to_delta=True,
            )

    # ── No-load active carriers ────────────────────────────────────────────────
    if await _rule_enabled("no_load_carrier_scan"):
        cutoff = now - timedelta(days=14)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Carrier).where(
                    Carrier.status == CarrierStatus.ACTIVE,
                    Carrier.is_blocked == False,
                )
            )
            active_carriers = result.scalars().all()

        for carrier in active_carriers:
            async with AsyncSessionLocal() as session:
                loads_result = await session.execute(
                    select(Load).where(
                        Load.carrier_mc == carrier.mc_number,
                        Load.created_at >= cutoff,
                    )
                )
                recent_loads = loads_result.scalars().all()

            if not recent_loads and carrier.phone:
                nova_sms(
                    carrier.phone,
                    f"Hi {carrier.name.split()[0]}, Erin here with Verlytax. "
                    f"We haven't seen any loads from you in the past two weeks — "
                    f"need help finding freight? Reply YES and I'll get on it."
                )
                log_automation(
                    agent="brain", action_type="no_load_carrier_sms",
                    description="No loads in 14 days — check-in SMS sent",
                    result="sent", carrier_mc=carrier.mc_number,
                )

    # ── Stale leads ───────────────────────────────────────────────────────────
    if await _rule_enabled("stale_lead_scan"):
        cutoff = now - timedelta(days=14)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Carrier).where(
                    Carrier.status == CarrierStatus.LEAD,
                    Carrier.created_at < cutoff,
                    Carrier.is_blocked == False,
                )
            )
            stale_leads = result.scalars().all()

        if stale_leads:
            lead_list = "\n".join(
                f"MC#{c.mc_number} — {c.name} | {c.phone or 'no phone'} | Created {c.created_at.strftime('%m/%d')}"
                for c in stale_leads
            )
            nova_alert_ceo(
                subject=f"Stale Leads — {len(stale_leads)} leads need follow-up",
                body=f"These leads have had no activity in 14+ days:\n\n{lead_list}",
            )
            for lead in stale_leads:
                log_automation(
                    agent="brain", action_type="stale_lead_alert",
                    description="Lead inactive 14+ days — Delta alerted",
                    result="escalated", carrier_mc=lead.mc_number, escalated_to_delta=True,
                )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    # Notify Delta that the system is live
    nova_alert_ceo(
        subject="Verlytax OS v4 — System Live",
        body="App started successfully on Railway. Erin, Nova, and Brain are online.",
    )

    # Start schedulers
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        friday_fee_charge,
        CronTrigger(day_of_week="fri", hour=10, minute=0, timezone="UTC"),
        id="friday_fee_charge",
        replace_existing=True,
    )
    scheduler.add_job(
        check_trial_touchpoints,
        CronTrigger(hour=9, minute=0, timezone="UTC"),
        id="trial_touchpoints",
        replace_existing=True,
    )
    scheduler.add_job(
        coi_expiry_check,
        CronTrigger(hour=7, minute=0, timezone="UTC"),
        id="coi_expiry_check",
        replace_existing=True,
    )
    scheduler.add_job(
        testimonial_sms,
        CronTrigger(hour=10, minute=30, timezone="UTC"),
        id="testimonial_sms",
        replace_existing=True,
    )
    scheduler.add_job(
        annual_fmcsa_recheck,
        CronTrigger(month=1, day=1, hour=6, minute=0, timezone="UTC"),
        id="annual_fmcsa_recheck",
        replace_existing=True,
    )
    scheduler.add_job(
        brain_autonomous_scan,
        CronTrigger(hour=8, minute=0, timezone="UTC"),
        id="brain_autonomous_scan",
        replace_existing=True,
    )
    scheduler.start()

    yield

    scheduler.shutdown(wait=False)


app = FastAPI(
    title="Verlytax OS v4",
    description="AI-Native Freight Dispatch — Erin, Nova, Brain",
    version="4.0.0",
    lifespan=lifespan,
    docs_url="/docs" if os.getenv("APP_ENV") != "production" else None,
    redoc_url=None,
)

# Static files (dashboard)
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Routers
app.include_router(onboarding.router, prefix="/onboarding", tags=["Onboarding"])
app.include_router(billing.router, prefix="/billing", tags=["Billing"])
app.include_router(escalation.router, prefix="/escalation", tags=["Escalation"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["Webhooks"])
app.include_router(carriers.router, prefix="/carriers", tags=["Carriers"])
app.include_router(brain.router, prefix="/brain", tags=["Brain"])
app.include_router(agents.router, prefix="/agents", tags=["Agents"])
app.include_router(workflows.router, prefix="/workflows", tags=["Workflows"])


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the Verlytax operations dashboard."""
    dashboard_path = os.path.join(static_dir, "dashboard.html")
    if os.path.exists(dashboard_path):
        with open(dashboard_path) as f:
            return f.read()
    return HTMLResponse("<h1>Verlytax OS v4</h1><p>Dashboard loading...</p>")


@app.get("/about", response_class=HTMLResponse)
async def about():
    """ClearRoute Dispatch public about page — PAS formula, trust badges, FAQs."""
    path = os.path.join(static_dir, "about.html")
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return HTMLResponse("<h1>About ClearRoute Dispatch</h1>")


@app.get("/carrier-packet", response_class=HTMLResponse)
async def carrier_packet():
    """Carrier services packet — onboarding, fees, Iron Standards, FAQ."""
    path = os.path.join(static_dir, "carrier-packet.html")
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return HTMLResponse("<h1>ClearRoute Carrier Packet</h1>")


@app.get("/shipper-broker-packet", response_class=HTMLResponse)
async def shipper_broker_packet():
    """Shipper and broker capacity packet — carrier standards, compliance docs, load submission."""
    path = os.path.join(static_dir, "shipper-broker-packet.html")
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return HTMLResponse("<h1>ClearRoute Broker Packet</h1>")


class ErinChatRequest(BaseModel):
    message: str


@app.post("/erin/chat")
async def erin_chat(req: ErinChatRequest):
    """Live chat with Erin — AI Dispatcher. Wired to dashboard chat box."""
    reply = await asyncio.to_thread(erin_respond, req.message)
    return {"reply": reply}


@app.post("/brain/setup-drive")
async def brain_setup_drive():
    """
    One-time Brain task: create top-level Google Drive folder structure.
    Run once after connecting Google service account. Idempotent — safe to re-run.
    """
    from app.gdrive import ensure_top_level_structure
    result = ensure_top_level_structure()
    return result


@app.get("/health")
async def health():
    return {"status": "ok", "system": "Verlytax OS v4", "version": "4.0.0"}


@app.get("/ping")
async def ping():
    return {"pong": True}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )
