"""
Verlytax OS v4 — FastAPI Application Entry Point
"You drive. We handle the rest."
"""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db import init_db, AsyncSessionLocal, Carrier, Load, CarrierStatus, LoadStatus
from app.routes import onboarding, billing, escalation, webhooks
from app.services import nova_alert_ceo, charge_carrier_fee, calculate_fee

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
                Carrier.status.in_([CarrierStatus.TRIAL, CarrierStatus.INACTIVE]),
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
                    c.status = CarrierStatus.INACTIVE
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
        CronTrigger(day_of_week="fri", hour=9, minute=0, timezone="America/New_York"),
        id="friday_fee_charge",
        replace_existing=True,
    )
    scheduler.add_job(
        check_trial_touchpoints,
        CronTrigger(hour=8, minute=0, timezone="America/New_York"),
        id="trial_touchpoints",
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
