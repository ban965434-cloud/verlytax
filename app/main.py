"""
Verlytax OS v4 — FastAPI Application Entry Point
"You drive. We handle the rest."
"""

import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db import init_db, AsyncSessionLocal, Carrier, Load, CarrierStatus, LoadStatus, AutomationRule, AutomationLog, AgentMemory, ComplianceAudit, SupportTicket
from app.routes import onboarding, billing, escalation, webhooks, carriers, brain, agents, workflows, mya, compliance, support, nova, auth
from app.routes.auth import verify_session
from app.services import nova_alert_ceo, nova_sms, charge_carrier_fee, calculate_fee, erin_respond, fmcsa_lookup, log_automation, store_memory, run_agent

from sqlalchemy import select
from datetime import datetime

# ── Lead Gen target states (Phase 1: Texas + Midwest + Southeast, no FL) ─────
LEAD_GEN_STATES = [
    "TX",                                    # Texas
    "IL", "IN", "OH", "MI", "MO",           # Midwest core
    "IA", "MN", "WI", "KS", "NE",           # Midwest extended
    "GA", "AL", "MS", "TN", "SC",           # Southeast
    "NC", "VA", "KY",                        # Southeast extended
]
MAX_LEADS_PER_STATE = 50
MAX_LEADS_PER_RUN = 200


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
                    trial_loads = loads_result.scalars().all()
                    load_count = len(trial_loads)

                first_name = c.name.split()[0]
                if load_count > 0:
                    gross = sum(l.rate_total or 0 for l in trial_loads)
                    avg_rpm = sum(l.rate_per_mile or 0 for l in trial_loads) / load_count
                    perf_line = (
                        f"You ran {load_count} load(s) with us this week — "
                        f"${gross:,.0f} gross, avg ${avg_rpm:.2f}/mi."
                    )
                else:
                    perf_line = "Trial wraps today — let's get your first load on the board."

                nova_sms(
                    c.phone,
                    f"Hi {first_name}, this is Erin with Verlytax. "
                    f"{perf_line} "
                    f"Ready to go active? Reply YES and I'll lock in your account. "
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
    """Check if an automation rule is enabled before running it.
    Always checks system_halt first — if Delta sent HALT, nothing runs."""
    async with AsyncSessionLocal() as session:
        # Master halt check — HALT command freezes all agents immediately
        halt_result = await session.execute(
            select(AutomationRule).where(AutomationRule.rule_key == "system_halt")
        )
        halt_rule = halt_result.scalar_one_or_none()
        if halt_rule and halt_rule.enabled:
            return False

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


async def mya_learn():
    """
    Daily at 6:00 AM UTC — Mya analyzes recent data and stores learnings.
    Synthesizes load outcomes, carrier behavior, disputes into AgentMemory.
    Rule key: mya_learn
    """
    if not await _rule_enabled("mya_learn"):
        return

    from datetime import timedelta
    now = datetime.utcnow()
    yesterday = now - timedelta(hours=24)

    async with AsyncSessionLocal() as session:
        loads_result = await session.execute(
            select(Load).where(Load.created_at >= yesterday)
        )
        recent_loads = loads_result.scalars().all()

        from app.db import EscalationLog
        esc_result = await session.execute(
            select(EscalationLog).where(EscalationLog.created_at >= yesterday)
        )
        recent_escalations = esc_result.scalars().all()

    if not recent_loads and not recent_escalations:
        return  # Nothing happened today — nothing to learn

    # Build data summary for Mya to analyze
    lines = [f"Analysis date: {now.strftime('%Y-%m-%d')}"]
    lines.append(f"Loads in last 24h: {len(recent_loads)}")
    for load in recent_loads:
        lines.append(
            f"  Load #{load.id}: {load.origin_state or '?'}→{load.destination_state or '?'} "
            f"${load.rate_total or 0:.0f} RPM:${load.rate_per_mile or 0:.2f} "
            f"Weight:{load.weight_lbs or 0:.0f}lbs Status:{load.status} MC:{load.carrier_mc}"
        )
    if recent_escalations:
        lines.append(f"\nEscalations/Disputes: {len(recent_escalations)}")
        for esc in recent_escalations:
            lines.append(
                f"  MC#{esc.carrier_mc}: {esc.issue_type} — {(esc.description or '')[:120]}"
            )

    summary = "\n".join(lines)
    prompt = (
        "Analyze this operational data from the past 24 hours. "
        "Identify 1–3 important patterns, risks, or insights worth remembering. "
        "Format each as: Pattern / Evidence / Implication / Recommended action. "
        "Be concise and specific. Only flag things that actually matter."
    )

    insights = await asyncio.to_thread(run_agent, "MYA.md", prompt, summary)

    if insights and "[Agent" not in insights:
        store_memory(
            agent="mya",
            memory_type="business_insight",
            subject=f"Daily learning — {now.strftime('%Y-%m-%d')}",
            content=insights,
            importance=3,
            source="auto",
        )
        log_automation(
            agent="mya",
            action_type="daily_learning",
            description=f"Mya synthesized insights from {len(recent_loads)} loads, {len(recent_escalations)} escalations",
            result="stored",
        )


async def cora_compliance_scan():
    """
    Weekly (Mondays 7:30 AM UTC) — Cora audits all active + trial carriers for compliance.
    GREEN: no action. YELLOW: SMS carrier + Delta summary. RED: suspend + immediate Delta alert.
    Rule key: cora_compliance_scan
    """
    if not await _rule_enabled("cora_compliance_scan"):
        return

    from app.routes.compliance import run_carrier_audit

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Carrier).where(
                Carrier.status.in_([CarrierStatus.ACTIVE, CarrierStatus.TRIAL]),
                Carrier.is_blocked == False,
            )
        )
        carriers_to_check = result.scalars().all()

    green, yellow, red = [], [], []

    for carrier in carriers_to_check:
        audit = run_carrier_audit(carrier)
        risk = audit["risk_level"]

        # Store audit record
        async with AsyncSessionLocal() as session:
            audit_record = ComplianceAudit(
                carrier_mc=carrier.mc_number,
                checked_by="cora",
                checked_at=datetime.utcnow(),
                authority_age_days=audit.get("authority_age_days"),
                authority_passed=audit.get("authority_passed", False),
                safety_rating=audit.get("safety_rating"),
                safety_passed=audit.get("safety_passed", False),
                clearinghouse_passed=audit.get("clearinghouse_passed", False),
                clearinghouse_data_age_days=audit.get("clearinghouse_data_age_days"),
                coi_expiry=audit.get("coi_expiry"),
                coi_valid=audit.get("coi_valid", False),
                coi_days_remaining=audit.get("coi_days_remaining"),
                insurance_auto_amount=audit.get("insurance_auto_amount"),
                insurance_auto_passed=audit.get("insurance_auto_passed", False),
                insurance_cargo_amount=audit.get("insurance_cargo_amount"),
                insurance_cargo_passed=audit.get("insurance_cargo_passed", False),
                nds_enrolled=audit.get("nds_enrolled", False),
                overall_passed=audit.get("overall_passed", False),
                risk_level=risk,
                violations=str(audit.get("violations", [])),
            )
            session.add(audit_record)

            if risk == "red":
                c = await session.get(Carrier, carrier.id)
                if c and c.status != CarrierStatus.SUSPENDED:
                    c.status = CarrierStatus.SUSPENDED
            await session.commit()

        if risk == "red":
            red.append(carrier)
            violations = audit.get("violations", [])
            if carrier.phone:
                nova_sms(
                    carrier.phone,
                    f"Hi {carrier.name.split()[0]}, this is Cora with Verlytax Compliance. "
                    f"Your account has been paused due to a compliance issue: {'; '.join(violations[:2])}. "
                    f"Please contact ops@verlytax.com immediately to reinstate your account."
                )
            nova_alert_ceo(
                subject=f"COMPLIANCE RED — MC#{carrier.mc_number} SUSPENDED",
                body=(
                    f"Carrier: {carrier.name} MC#{carrier.mc_number}\n"
                    f"Violations: {chr(10).join(violations)}\n"
                    f"Status: Suspended immediately. Only Delta can reinstate."
                ),
            )
            log_automation(
                agent="cora", action_type="compliance_red",
                description=f"Suspended: {'; '.join(violations[:3])}",
                result="suspended", carrier_mc=carrier.mc_number, escalated_to_delta=True,
            )

        elif risk == "yellow":
            yellow.append(carrier)
            warnings = audit.get("violations", [])
            if carrier.phone:
                nova_sms(
                    carrier.phone,
                    f"Hi {carrier.name.split()[0]}, this is Cora with Verlytax Compliance. "
                    f"Action needed: {'; '.join(warnings[:2])}. "
                    f"Please update your documents at ops@verlytax.com within 7 days to avoid a dispatch hold."
                )
            log_automation(
                agent="cora", action_type="compliance_yellow",
                description=f"Warning: {'; '.join(warnings[:3])}",
                result="warned", carrier_mc=carrier.mc_number,
            )

        else:
            green.append(carrier.mc_number)

    if yellow or red:
        nova_alert_ceo(
            subject=f"Cora Weekly Scan — {len(red)} RED, {len(yellow)} YELLOW",
            body=(
                f"Compliance scan complete. {len(carriers_to_check)} carriers checked.\n\n"
                f"RED (suspended): {', '.join(f'MC#{c.mc_number}' for c in red) or 'none'}\n"
                f"YELLOW (warned): {', '.join(f'MC#{c.mc_number}' for c in yellow) or 'none'}\n"
                f"GREEN: {len(green)}"
            ),
        )

    log_automation(
        agent="cora", action_type="weekly_scan_complete",
        description=f"Checked {len(carriers_to_check)}: {len(green)} green, {len(yellow)} yellow, {len(red)} red",
        result="complete",
    )


async def support_ticket_sweep():
    """
    Daily at 9:30 AM UTC — Zara follows up on open tickets and auto-escalates stale ones.
    Rule key: support_ticket_sweep
    """
    if not await _rule_enabled("support_ticket_sweep"):
        return

    from datetime import timedelta
    now = datetime.utcnow()
    over_24h = now - timedelta(hours=24)
    over_48h = now - timedelta(hours=48)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SupportTicket).where(
                SupportTicket.status.in_(["open", "in_progress"]),
                SupportTicket.created_at <= over_24h,
            )
        )
        stale_tickets = result.scalars().all()

    for ticket in stale_tickets:
        async with AsyncSessionLocal() as session:
            t = await session.get(SupportTicket, ticket.id)
            if not t:
                continue

            # Auto-escalate tickets over 48h with no resolution
            if t.created_at <= over_48h and t.status != "escalated":
                t.status = "escalated"
                t.assigned_to = "delta"
                t.escalation_reason = "Auto-escalated: open >48 hours with no resolution"
                t.updated_at = now
                await session.commit()
                nova_alert_ceo(
                    subject=f"Ticket Auto-Escalated — {t.ticket_number}",
                    body=(
                        f"Ticket {t.ticket_number} has been open 48+ hours with no resolution.\n"
                        f"Carrier: MC#{t.carrier_mc or 'unknown'}\n"
                        f"Subject: {t.subject}\n"
                        f"Category: {t.category} | Priority: {t.priority}"
                    ),
                )
                log_automation(
                    agent="zara", action_type="ticket_auto_escalated",
                    description=f"{t.ticket_number} auto-escalated after 48h",
                    result="escalated", carrier_mc=t.carrier_mc, escalated_to_delta=True,
                )

            elif t.status in ("open", "in_progress") and t.phone:
                # Send follow-up SMS for tickets open 24-48h
                nova_sms(
                    t.phone,
                    f"Hi, this is Zara with Verlytax Support following up on ticket {t.ticket_number}: "
                    f"\"{t.subject}\". We're still working on this and will have a resolution shortly. "
                    f"Reply anytime with updates."
                )
                log_automation(
                    agent="zara", action_type="ticket_followup_sms",
                    description=f"{t.ticket_number} follow-up SMS sent (open >24h)",
                    result="sent", carrier_mc=t.carrier_mc,
                )


async def megan_sdr_outreach():
    """
    Daily at 11:00 AM UTC — Megan auto-contacts stale leads (no activity in 14+ days).
    Pulls up to 20 leads per run, drafts personalized SMS via Claude, sends via Nova.
    Rule key: megan_sdr_outreach
    """
    if not await _rule_enabled("megan_sdr_outreach"):
        return

    from datetime import timedelta

    now = datetime.utcnow()
    cutoff = now - timedelta(days=14)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Carrier).where(
                Carrier.status == CarrierStatus.LEAD,
                Carrier.phone.isnot(None),
                Carrier.is_blocked == False,
                Carrier.created_at < cutoff,
            ).limit(20)
        )
        leads = result.scalars().all()

    if not leads:
        log_automation(
            agent="megan_sdr", action_type="daily_sdr_outreach",
            description="Daily SDR run — no stale leads found", result="skipped",
        )
        return

    sent, failed = [], []

    for lead in leads:
        try:
            context = (
                f"Carrier: {lead.name} | MC#{lead.mc_number}\n"
                f"Phone: {lead.phone}\n"
                f"Lead since: {lead.created_at.strftime('%B %d, %Y')}\n"
                f"Days as lead: {(now - lead.created_at).days}\n"
                f"Notes: {lead.notes or 'none'}"
            )
            prompt = (
                f"Draft a short, professional outbound SMS to {lead.name} (MC#{lead.mc_number}) "
                f"who has been a lead for {(now - lead.created_at).days} days with no conversion. "
                f"Re-engage them — be specific, warm, and close with one clear next step."
            )
            draft = await asyncio.to_thread(run_agent, "SDR_MEGAN.md", prompt, context)
            nova_sms(lead.phone, draft)
            sent.append(f"{lead.name} MC#{lead.mc_number}")
            log_automation(
                agent="megan_sdr", action_type="daily_sdr_outreach",
                description=f"Outreach SMS sent to {lead.name} MC#{lead.mc_number}",
                result="sent", carrier_mc=lead.mc_number,
            )
        except Exception as e:
            failed.append(f"{lead.name} MC#{lead.mc_number}")
            log_automation(
                agent="megan_sdr", action_type="daily_sdr_outreach",
                description=f"Outreach failed for {lead.name} MC#{lead.mc_number}: {str(e)}",
                result="error", carrier_mc=lead.mc_number,
            )

    nova_alert_ceo(
        subject=f"Megan SDR Daily Run — {len(sent)}/{len(leads)} sent",
        body=(
            f"Daily outreach complete.\n"
            f"Sent ({len(sent)}): {', '.join(sent) or 'none'}\n"
            f"Failed ({len(failed)}): {', '.join(failed) or 'none'}"
        ),
    )


async def fmcsa_lead_gen():
    """
    Daily at 6:30 AM UTC — queries FMCSA (and DAT when key is set) for qualifying dry van
    carriers across target states and auto-seeds them as LEAD in the DB.
    Runs 30 min before compliance scans, 4.5 hrs before Megan's outreach.
    Rule key: fmcsa_lead_gen
    """
    if not await _rule_enabled("fmcsa_lead_gen"):
        return

    now = datetime.utcnow()
    new_count = 0
    skipped_count = 0
    states_queried = []

    async with AsyncSessionLocal() as session:
        for state in LEAD_GEN_STATES:
            if new_count >= MAX_LEADS_PER_RUN:
                break

            fmcsa_results = await fmcsa_search_carriers(state, limit=MAX_LEADS_PER_STATE)
            dat_results = await dat_search_carriers([state], limit=MAX_LEADS_PER_STATE)
            combined = {c["mc_number"]: c for c in fmcsa_results + dat_results}  # dedup by MC#

            if not combined:
                continue
            states_queried.append(state)

            for mc_number, lead in combined.items():
                if new_count >= MAX_LEADS_PER_RUN:
                    break
                # Skip if already in DB
                existing = await session.execute(
                    select(Carrier).where(Carrier.mc_number == mc_number)
                )
                if existing.scalar_one_or_none():
                    skipped_count += 1
                    continue

                session.add(Carrier(
                    mc_number=mc_number,
                    name=lead["name"],
                    phone=lead.get("phone") or None,
                    dot_number=lead.get("dot_number") or None,
                    truck_type="dry_van",
                    status=CarrierStatus.LEAD,
                    notes=(
                        f"Auto-generated lead via {lead.get('source', 'fmcsa').upper()} — "
                        f"State: {lead.get('state', state)} — "
                        f"Authority age: {lead.get('authority_age_days') or 'unknown'} days — "
                        f"Seeded: {now.strftime('%Y-%m-%d')}"
                    ),
                ))
                new_count += 1

        await session.commit()

    log_automation(
        agent="mya",
        action_type="fmcsa_lead_gen",
        description=f"Lead gen ran across {len(states_queried)} states",
        result=f"{new_count} new leads added, {skipped_count} duplicates skipped",
    )

    if new_count > 0:
        nova_alert_ceo(
            subject=f"Lead Gen — {new_count} new carriers added",
            body=(
                f"Daily FMCSA/DAT lead gen complete.\n"
                f"New leads: {new_count}\n"
                f"Skipped (duplicates): {skipped_count}\n"
                f"States queried: {', '.join(states_queried) or 'none'}\n"
                f"Megan will contact stale leads at 11:00 AM UTC."
            ),
        )


async def daily_brief():
    """
    Daily at 6:00 AM UTC — sends Delta a revenue and operations snapshot via Nova.
    Every number traces to verlytax.db. No estimates.
    Rule key: daily_brief
    """
    if not await _rule_enabled("daily_brief"):
        return

    from datetime import timedelta
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)

    async with AsyncSessionLocal() as session:
        active_result = await session.execute(
            select(Carrier).where(Carrier.status == CarrierStatus.ACTIVE)
        )
        active_carriers = active_result.scalars().all()

        trial_result = await session.execute(
            select(Carrier).where(Carrier.status == CarrierStatus.TRIAL)
        )
        trial_carriers = trial_result.scalars().all()

        lead_result = await session.execute(
            select(Carrier).where(Carrier.status == CarrierStatus.LEAD)
        )
        lead_carriers = lead_result.scalars().all()

        loads_result = await session.execute(
            select(Load).where(Load.created_at >= week_ago)
        )
        recent_loads = loads_result.scalars().all()

        from app.db import EscalationLog
        esc_result = await session.execute(
            select(EscalationLog).where(EscalationLog.status != "resolved")
        )
        open_escalations = esc_result.scalars().all()

        # Check if system is halted
        halt_result = await session.execute(
            select(AutomationRule).where(AutomationRule.rule_key == "system_halt")
        )
        halt_rule = halt_result.scalar_one_or_none()
        is_halted = halt_rule and halt_rule.enabled

    in_transit = [l for l in recent_loads if l.status == LoadStatus.IN_TRANSIT]
    delivered_week = [l for l in recent_loads if l.status in (
        LoadStatus.DELIVERED, LoadStatus.INVOICED, LoadStatus.PAID
    )]
    paid_week = [l for l in recent_loads if l.status == LoadStatus.PAID]
    revenue_collected = sum(l.verlytax_fee or 0 for l in paid_week)

    expiring_soon = [
        c for c in active_carriers
        if c.coi_expiry and (c.coi_expiry - now).days <= 30
    ]

    lines = [
        f"VERLYTAX DAILY BRIEF — {now.strftime('%a %b %d')}",
        f"Agents: {'HALTED ⛔' if is_halted else 'RUNNING ✓'}",
        f"Active: {len(active_carriers)} | Trial: {len(trial_carriers)} | Leads: {len(lead_carriers)}",
        f"In Transit: {len(in_transit)} | Delivered (7d): {len(delivered_week)}",
        f"Revenue Collected (7d): ${revenue_collected:.2f}",
        f"Open Escalations: {len(open_escalations)}",
    ]
    if expiring_soon:
        lines.append(f"COI Expiring <30d: {', '.join(c.mc_number for c in expiring_soon)}")

    nova_alert_ceo(subject="Daily Brief", body="\n".join(lines))
    log_automation(
        agent="nova",
        action_type="daily_brief",
        description=f"Daily brief — {len(active_carriers)} active, {len(in_transit)} in transit, ${revenue_collected:.2f} collected",
        result="sent",
    )


async def mya_weekly_score():
    """
    Weekly Sunday 3:00 AM UTC — Mya deep scores brokers, lanes, and carriers
    from full historical load data. Writes 3 structured memory types.
    Rule key: mya_learn
    """
    if not await _rule_enabled("mya_learn"):
        return

    now = datetime.utcnow()

    async with AsyncSessionLocal() as session:
        all_loads_result = await session.execute(select(Load))
        all_loads = all_loads_result.scalars().all()

        active_carriers_result = await session.execute(
            select(Carrier).where(Carrier.status.in_([CarrierStatus.ACTIVE, CarrierStatus.TRIAL]))
        )
        active_carriers = active_carriers_result.scalars().all()

    if not all_loads:
        return

    # ── Broker scoring ──────────────────────────────────────────────────────────
    broker_data: dict = {}
    for load in all_loads:
        if not load.broker_name:
            continue
        b = broker_data.setdefault(load.broker_name, {"loads": 0, "total_rpm": 0.0})
        b["loads"] += 1
        b["total_rpm"] += load.rate_per_mile or 0

    if broker_data:
        broker_lines = []
        for name, d in sorted(broker_data.items(), key=lambda x: -x[1]["loads"])[:20]:
            avg_rpm = d["total_rpm"] / d["loads"]
            broker_lines.append(f"{name}: {d['loads']} loads | avg ${avg_rpm:.2f}/mi")
        broker_insight = await asyncio.to_thread(
            run_agent, "MYA.md",
            "Score these brokers from best to worst based on volume and RPM. Flag any to avoid.",
            "Weekly broker data:\n" + "\n".join(broker_lines),
        )
        store_memory(agent="mya", memory_type="broker_score",
            subject=f"Broker scores — {now.strftime('%Y-%m-%d')}",
            content=broker_insight, importance=4, source="weekly_score")

    # ── Lane scoring ────────────────────────────────────────────────────────────
    lane_data: dict = {}
    for load in all_loads:
        if not load.origin_state or not load.destination_state:
            continue
        lane = f"{load.origin_state}→{load.destination_state}"
        l = lane_data.setdefault(lane, {"loads": 0, "total_rpm": 0.0})
        l["loads"] += 1
        l["total_rpm"] += load.rate_per_mile or 0

    if lane_data:
        lane_lines = []
        for lane, d in sorted(lane_data.items(), key=lambda x: -x[1]["loads"])[:20]:
            avg_rpm = d["total_rpm"] / d["loads"]
            lane_lines.append(f"{lane}: {d['loads']} loads | avg ${avg_rpm:.2f}/mi")
        lane_insight = await asyncio.to_thread(
            run_agent, "MYA.md",
            "Rank these lanes by profitability and volume. Identify top 5 priority lanes and any to deprioritize.",
            "Weekly lane data:\n" + "\n".join(lane_lines),
        )
        store_memory(agent="mya", memory_type="lane_insight",
            subject=f"Lane scores — {now.strftime('%Y-%m-%d')}",
            content=lane_insight, importance=4, source="weekly_score")

    # ── Carrier scoring ─────────────────────────────────────────────────────────
    carrier_lines = []
    for carrier in active_carriers:
        carrier_loads = [l for l in all_loads if l.carrier_mc == carrier.mc_number]
        if not carrier_loads:
            continue
        avg_rpm = sum(l.rate_per_mile or 0 for l in carrier_loads) / len(carrier_loads)
        carrier_lines.append(
            f"MC#{carrier.mc_number} {carrier.name}: {len(carrier_loads)} loads | avg ${avg_rpm:.2f}/mi | status:{carrier.status}"
        )

    if carrier_lines:
        carrier_insight = await asyncio.to_thread(
            run_agent, "MYA.md",
            "Analyze carrier performance. Flag underperformers and at-risk carriers. Identify top performers.",
            "Weekly carrier data:\n" + "\n".join(carrier_lines[:30]),
        )
        store_memory(agent="mya", memory_type="carrier_profile",
            subject=f"Carrier scores — {now.strftime('%Y-%m-%d')}",
            content=carrier_insight, importance=4, source="weekly_score")

    log_automation(
        agent="mya", action_type="weekly_score",
        description=f"Weekly deep score: {len(broker_data)} brokers, {len(lane_data)} lanes, {len(carrier_lines)} carriers",
        result="stored",
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
    scheduler.add_job(
        daily_brief,
        CronTrigger(hour=6, minute=0, timezone="UTC"),
        id="daily_brief",
        replace_existing=True,
    )
    scheduler.add_job(
        mya_learn,
        CronTrigger(hour=6, minute=10, timezone="UTC"),
        id="mya_learn",
        replace_existing=True,
    )
    scheduler.add_job(
        mya_weekly_score,
        CronTrigger(day_of_week="sun", hour=3, minute=0, timezone="UTC"),
        id="mya_weekly_score",
        replace_existing=True,
    )
    scheduler.add_job(
        cora_compliance_scan,
        CronTrigger(day_of_week="mon", hour=7, minute=30, timezone="UTC"),
        id="cora_compliance_scan",
        replace_existing=True,
    )
    scheduler.add_job(
        support_ticket_sweep,
        CronTrigger(hour=9, minute=30, timezone="UTC"),
        id="support_ticket_sweep",
        replace_existing=True,
    )
    scheduler.add_job(
        megan_sdr_outreach,
        CronTrigger(hour=11, minute=0, timezone="UTC"),
        id="megan_sdr_outreach",
        replace_existing=True,
    )
    scheduler.add_job(
        fmcsa_lead_gen,
        CronTrigger(hour=6, minute=30, timezone="UTC"),
        id="fmcsa_lead_gen",
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
app.include_router(mya.router, prefix="/mya", tags=["Mya"])
app.include_router(compliance.router, prefix="/compliance", tags=["Compliance"])
app.include_router(support.router, prefix="/support", tags=["Support"])
app.include_router(nova.router, prefix="/nova", tags=["Nova"])
app.include_router(auth.router, prefix="/auth", tags=["Auth"])


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Serve the CEO login page. Redirects to dashboard if already signed in."""
    if verify_session(request.cookies.get("vx_session")):
        return RedirectResponse("/", status_code=302)
    path = os.path.join(static_dir, "login.html")
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return HTMLResponse("<form method='POST' action='/auth/login'><input name='username'><input name='password' type='password'><button>Login</button></form>")


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Serve the Verlytax operations dashboard — CEO-only, requires active session."""
    if not verify_session(request.cookies.get("vx_session")):
        return RedirectResponse("/login", status_code=302)
    dashboard_path = os.path.join(static_dir, "dashboard.html")
    if os.path.exists(dashboard_path):
        with open(dashboard_path) as f:
            return f.read()
    return HTMLResponse("<h1>Verlytax OS v4</h1><p>Dashboard loading...</p>")


@app.get("/about", response_class=HTMLResponse)
async def about():
    """Verlytax Dispatch public about page — PAS formula, trust badges, FAQs."""
    path = os.path.join(static_dir, "about.html")
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return HTMLResponse("<h1>About Verlytax Dispatch</h1>")


@app.get("/carrier-packet", response_class=HTMLResponse)
async def carrier_packet():
    """Carrier services packet — onboarding, fees, Iron Standards, FAQ."""
    path = os.path.join(static_dir, "carrier-packet.html")
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return HTMLResponse("<h1>Verlytax Carrier Packet</h1>")


@app.get("/shipper-broker-packet", response_class=HTMLResponse)
async def shipper_broker_packet():
    """Shipper and broker capacity packet — carrier standards, compliance docs, load submission."""
    path = os.path.join(static_dir, "shipper-broker-packet.html")
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return HTMLResponse("<h1>Verlytax Broker Packet</h1>")


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
