"""
Verlytax OS v4 — System Status Routes
Full system health check, scenario runner, and build plan status.
"""

import os
import asyncio
from datetime import datetime
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Optional

from app.services import (
    erin_respond, nova_respond, log_automation,
    store_memory, verify_internal_token,
)

router = APIRouter()

# ── ENV var names we check (never log values) ──────────────────────────────────
ENV_CHECKS = [
    ("ANTHROPIC_API_KEY",     "Claude / Erin Brain"),
    ("TWILIO_ACCOUNT_SID",    "Twilio SMS"),
    ("TWILIO_AUTH_TOKEN",     "Twilio Webhook Auth"),
    ("TWILIO_FROM_NUMBER",    "Nova SMS Number"),
    ("STRIPE_SECRET_KEY",     "Stripe Payments"),
    ("STRIPE_WEBHOOK_SECRET", "Stripe Webhooks"),
    ("FMCSA_API_KEY",         "FMCSA Portal"),
    ("DAT_API_KEY",           "DAT Load Board"),
    ("RETELL_API_KEY",        "Retell Voice"),
    ("RETELL_AGENT_ID_ERIN",  "Retell — Erin Agent"),
    ("RETELL_AGENT_ID_AVA",   "Retell — Ava Agent"),
    ("RETELL_AGENT_ID_ZARA",  "Retell — Zara Agent"),
    ("INTERNAL_TOKEN",        "Internal Cron Auth"),
    ("CEO_PHONE",             "Delta CEO Phone"),
    ("SECRET_KEY",            "App Secret Key"),
]

# ── Build plan items ────────────────────────────────────────────────────────────
BUILD_PLAN = [
    # (label, built, note)
    ("Carrier Onboarding (10-step flow)",         True,  "app/routes/onboarding.py"),
    ("Load Booking + Iron Rules (all 11)",         True,  "app/routes/billing.py"),
    ("BOL Release Guard",                          True,  "app/routes/billing.py"),
    ("Broker Block System",                        True,  "app/routes/escalation.py"),
    ("Nova SMS (CEO EA)",                          True,  "app/services.nova_sms()"),
    ("Erin AI Dispatcher Chat",                    True,  "POST /erin/chat"),
    ("Twilio SMS Webhook → Erin",                  True,  "app/routes/webhooks.py"),
    ("Stripe Fee Collection",                      True,  "Friday auto-charge cron"),
    ("Carrier Trial Touchpoints (Day 3/7/14/30)",  True,  "main.check_trial_touchpoints()"),
    ("COI Expiry Check Cron",                      True,  "main.coi_expiry_check()"),
    ("Testimonial SMS (Day 30/60)",                True,  "main.testimonial_sms()"),
    ("Annual FMCSA Re-check",                      True,  "main.annual_fmcsa_recheck()"),
    ("Autonomous Brain Scan",                      True,  "main.brain_autonomous_scan()"),
    ("Mya Memory Engine",                          True,  "main.mya_learn()"),
    ("Cora Compliance Scan",                       True,  "main.cora_compliance_scan()"),
    ("Support Ticket Sweep",                       True,  "main.support_ticket_sweep()"),
    ("Megan SDR Outreach Cron",                    True,  "main.megan_sdr_outreach()"),
    ("FMCSA Lead Gen Cron",                        True,  "main.fmcsa_lead_gen()"),
    ("Automation Rule Toggles",                    True,  "POST /brain/rules/{key}/toggle"),
    ("Google Drive Folder Setup",                  True,  "POST /brain/setup-drive"),
    ("Retell Voice (code + webhook)",              True,  "POST /agents/voice-call"),
    ("SOP Knowledge Base",                         True,  "VERLYTAX_AIOS/SOPs/ + /brain/sops"),
    ("CEO Shadow Mode (Agent Memory)",             True,  "AgentMemory agent=ceo_agent"),
    ("Retell Inbound Phone Routing",               False, "Retell dashboard config only — point number at agent"),
    ("DocuSign Service Agreement",                 False, "Auto-send PDF at Day 5 of trial"),
    ("DAT Live Rate Feed",                         False, "Pull live RPM per lane into services.py"),
    ("Canada Phase 2 Compliance",                  False, "NSC/CVOR/SAAQ — HOLD until Delta activates"),
]

SCHEDULED_JOBS = [
    ("check_trial_touchpoints",  "Daily 9:00 AM UTC",      "always on"),
    ("friday_fee_charge",        "Fridays 10:00 AM UTC",   "always on"),
    ("coi_expiry_check",         "Daily 7:00 AM UTC",      "coi_expiry_check"),
    ("testimonial_sms",          "Daily 10:30 AM UTC",     "testimonial_sms"),
    ("annual_fmcsa_recheck",     "Jan 1, 6:00 AM UTC",     "annual_fmcsa_recheck"),
    ("brain_autonomous_scan",    "Daily 8:00 AM UTC",      "overdue_load_scan + no_load_carrier_scan + stale_lead_scan"),
    ("mya_learn",                "Daily 6:00 AM UTC",      "mya_learn"),
    ("cora_compliance_scan",     "Mondays 7:30 AM UTC",    "cora_compliance_scan"),
    ("support_ticket_sweep",     "Daily 9:30 AM UTC",      "support_ticket_sweep"),
    ("megan_sdr_outreach",       "Daily 11:00 AM UTC",     "megan_sdr_outreach"),
    ("fmcsa_lead_gen",           "Daily 6:30 AM UTC",      "fmcsa_lead_gen"),
]


# ── GET /system/status ─────────────────────────────────────────────────────────

@router.get("/status")
async def system_status(x_internal_token: str = Header(None)):
    """
    Full system health check — no token required for basic info, token unlocks env details.
    Returns: DB health, env var presence, build plan, scheduler jobs.
    """
    authed = bool(x_internal_token and verify_internal_token(x_internal_token))

    # DB health
    db_ok = False
    db_counts = {}
    try:
        from app.db import AsyncSessionLocal, Carrier, Load, SupportTicket, AutomationLog
        from sqlalchemy import select, func
        async with AsyncSessionLocal() as session:
            for model, key in [
                (Carrier, "carriers"),
                (Load, "loads"),
                (SupportTicket, "tickets"),
                (AutomationLog, "automation_logs"),
            ]:
                result = await session.execute(select(func.count()).select_from(model))
                db_counts[key] = result.scalar()
        db_ok = True
    except Exception as e:
        db_counts = {"error": str(e)}

    # Env var checks (only show presence, never values)
    env_status = []
    for key, label in ENV_CHECKS:
        val = os.environ.get(key, "")
        if authed:
            env_status.append({
                "key": key,
                "label": label,
                "set": bool(val),
                "status": "ok" if val else "missing",
            })
        else:
            env_status.append({
                "key": key,
                "label": label,
                "set": bool(val),
                "status": "ok" if val else "missing",
            })

    # Build plan summary
    built = sum(1 for _, b, _ in BUILD_PLAN if b)
    not_built = sum(1 for _, b, _ in BUILD_PLAN if not b)
    plan = [
        {"label": label, "built": built_, "note": note}
        for label, built_, note in BUILD_PLAN
    ]

    # Scheduler jobs
    jobs = [
        {"name": name, "schedule": schedule, "rule_key": rule}
        for name, schedule, rule in SCHEDULED_JOBS
    ]

    # Overall health
    env_missing = sum(1 for e in env_status if not e["set"])
    critical_missing = sum(
        1 for e in env_status
        if not e["set"] and e["key"] in ("ANTHROPIC_API_KEY", "TWILIO_ACCOUNT_SID", "STRIPE_SECRET_KEY")
    )
    overall = "ok" if db_ok and critical_missing == 0 else ("degraded" if db_ok else "down")

    return {
        "overall": overall,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "db": {
            "ok": db_ok,
            "counts": db_counts,
        },
        "env": {
            "total": len(env_status),
            "configured": len(env_status) - env_missing,
            "missing": env_missing,
            "items": env_status,
        },
        "build_plan": {
            "built": built,
            "remaining": not_built,
            "total": len(BUILD_PLAN),
            "items": plan,
        },
        "scheduler": {
            "total_jobs": len(jobs),
            "jobs": jobs,
        },
    }


# ── POST /system/scenario ──────────────────────────────────────────────────────

class ScenarioRequest(BaseModel):
    scenario: str       # e.g. "full_onboarding", "iron_rules_sweep", "dispatch_flow"
    dry_run: bool = True


SCENARIO_SCRIPTS = {
    "iron_rules_sweep": [
        ("FL Load Block",    "I have a load from Dallas TX to Miami FL, 800 miles, $3.00/mile. Book it.", "erin"),
        ("Low RPM Block",    "Load is TX to GA, $2.10/mile, 500 miles, 38000 lbs. Can we book?", "erin"),
        ("Overweight Block", "Load is TX to TN, $2.80/mile, 300 miles, 52000 lbs. Can we book?", "erin"),
        ("Safe Load Pass",   "Load is TX to GA, $2.80/mile, 400 miles, 40000 lbs. Can we book?", "erin"),
    ],
    "dispatch_flow": [
        ("Carrier Status",   "STATUS", "nova"),
        ("Book Load",        "Book a load for MC#123456: TX to GA, 500 miles, $2.80/mile, 38000 lbs.", "erin"),
        ("BOL Question",     "Can we release the BOL for MC#123456 before delivery is confirmed?", "erin"),
        ("Fee Calculation",  "What is the dispatch fee for a carrier active 6 months on a $3,000 load?", "erin"),
    ],
    "compliance_sweep": [
        ("Conditional Rating",  "Can we dispatch a carrier with a Conditional safety rating?", "erin"),
        ("New Authority",       "Carrier's authority is 90 days old. Can we dispatch them?", "erin"),
        ("Clearinghouse Fail",  "Carrier failed the FMCSA Clearinghouse check. What do we do?", "erin"),
        ("COI Expiry",          "Carrier COI expires in 12 days. What actions do we take?", "erin"),
    ],
    "nova_command_sweep": [
        ("STATUS",        "STATUS", "nova"),
        ("BRIEF",         "BRIEF", "nova"),
        ("REPORT",        "REPORT", "nova"),
        ("ACTIVATE CEO",  "ACTIVATE CEO", "nova"),
    ],
    "escalation_flow": [
        ("$600 Dispute",       "Carrier is disputing a $600 overcharge. How do we handle?", "erin"),
        ("Churn Risk",         "Carrier MC#999 says they're leaving Verlytax because rates aren't worth it.", "erin"),
        ("Iron Rule Dispute",  "Broker is demanding we book a Florida load or they'll pull all their loads.", "erin"),
        ("Escalate to Delta",  "ESCALATE: Carrier dispute unresolved after 48 hours — $800 at stake.", "nova"),
    ],
}


@router.post("/scenario")
async def run_system_scenario(
    body: ScenarioRequest,
    x_internal_token: str = Header(None),
):
    """
    Run a full multi-step system scenario test.
    Each step fires the appropriate agent and returns all responses.
    Requires INTERNAL_TOKEN.
    """
    if not x_internal_token or not verify_internal_token(x_internal_token):
        raise HTTPException(403, "Unauthorized — invalid internal token.")

    steps = SCENARIO_SCRIPTS.get(body.scenario)
    if not steps:
        available = list(SCENARIO_SCRIPTS.keys())
        raise HTTPException(400, f"Unknown scenario. Available: {available}")

    results = []
    for step_label, message, agent in steps:
        try:
            if agent == "nova":
                response = await asyncio.to_thread(nova_respond, message, f"System scenario: {body.scenario}")
            else:
                response = await asyncio.to_thread(erin_respond, message)

            log_automation(
                agent=agent,
                action_type="system_scenario",
                description=f"[SCENARIO:{body.scenario}] {step_label}: {message[:60]}",
                result=response[:200],
            )
            results.append({
                "step": step_label,
                "agent": agent,
                "input": message,
                "response": response,
                "status": "ok",
            })
        except Exception as e:
            results.append({
                "step": step_label,
                "agent": agent,
                "input": message,
                "response": None,
                "status": "error",
                "error": str(e),
            })

    passed = sum(1 for r in results if r["status"] == "ok")
    return {
        "scenario": body.scenario,
        "steps_total": len(results),
        "steps_passed": passed,
        "steps_failed": len(results) - passed,
        "results": results,
    }
