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

    # Start Friday auto-charge scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        friday_fee_charge,
        CronTrigger(day_of_week="fri", hour=9, minute=0, timezone="America/New_York"),
        id="friday_fee_charge",
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
