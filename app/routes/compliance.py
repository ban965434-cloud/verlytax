"""
Verlytax OS v4 — Cora: Compliance Department
Full carrier compliance auditing — authority, safety, clearinghouse, COI, insurance, NDS.
Cora catches compliance risks before they become violations or liability.
"""

import json
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.db import (
    get_db, Carrier, CarrierStatus, ComplianceAudit,
    AutomationLog,
)
from app.services import verify_internal_token, nova_sms, nova_alert_ceo, log_automation

router = APIRouter()

# Compliance thresholds
MIN_AUTO_LIABILITY = 1_000_000.0    # Iron Rule — $1M minimum auto liability
MIN_CARGO_COVERAGE = 100_000.0      # Iron Rule — $100K minimum cargo coverage
MIN_AUTHORITY_DAYS = 180            # Iron Rule 6 — 180+ days
CLEARINGHOUSE_WARN_DAYS = 90        # Warn if clearinghouse data is 90+ days old
COI_RED_DAYS = 30                   # Suspend if COI expires within 30 days
COI_YELLOW_DAYS = 60                # Warn if COI expires within 31–60 days


# ── Core Audit Logic ──────────────────────────────────────────────────────────

def run_carrier_audit(carrier: Carrier) -> dict:
    """
    Run a full compliance audit on a carrier object.
    Returns structured audit result — does NOT write to DB (caller does that).
    """
    now = datetime.utcnow()
    violations = []
    warnings = []

    # ── Authority age (Iron Rule 6/10) ────────────────────────────────────────
    authority_age_days = None
    authority_passed = False
    if carrier.authority_granted_date:
        authority_age_days = (now - carrier.authority_granted_date).days
        if authority_age_days >= MIN_AUTHORITY_DAYS:
            authority_passed = True
        else:
            violations.append(f"Authority age {authority_age_days} days — must be {MIN_AUTHORITY_DAYS}+ (Iron Rule 6)")
    else:
        violations.append("Authority granted date not on file — cannot verify (Iron Rule 10)")

    # ── Safety rating (Iron Rule 5) ───────────────────────────────────────────
    safety_rating = str(carrier.safety_rating or "none").lower()
    safety_passed = safety_rating not in ("unsatisfactory", "conditional")
    if not safety_passed:
        violations.append(f"Safety rating is {safety_rating.upper()} — hard reject (Iron Rule 5)")

    # ── FMCSA Clearinghouse (Iron Rule 7) ─────────────────────────────────────
    clearinghouse_passed = carrier.clearinghouse_passed or False
    clearinghouse_data_age_days = None
    if carrier.clearinghouse_checked_at:
        clearinghouse_data_age_days = (now - carrier.clearinghouse_checked_at).days
        if clearinghouse_data_age_days >= CLEARINGHOUSE_WARN_DAYS:
            warnings.append(f"Clearinghouse data is {clearinghouse_data_age_days} days old — re-check recommended")
    if not clearinghouse_passed:
        violations.append("FMCSA Clearinghouse check not passed (Iron Rule 7)")

    # ── COI expiry ────────────────────────────────────────────────────────────
    coi_valid = False
    coi_days_remaining = None
    if carrier.coi_expiry:
        coi_days_remaining = (carrier.coi_expiry - now).days
        coi_valid = coi_days_remaining > 0
        if coi_days_remaining <= 0:
            violations.append(f"COI has EXPIRED ({abs(coi_days_remaining)} days ago)")
        elif coi_days_remaining <= COI_RED_DAYS:
            violations.append(f"COI expires in {coi_days_remaining} days — CRITICAL")
        elif coi_days_remaining <= COI_YELLOW_DAYS:
            warnings.append(f"COI expires in {coi_days_remaining} days — renewal required soon")
    else:
        violations.append("COI expiry date not on file")

    # ── Insurance minimums ────────────────────────────────────────────────────
    auto_amt = carrier.auto_liability_amount or 0.0
    cargo_amt = carrier.cargo_coverage_amount or 0.0
    insurance_auto_passed = auto_amt >= MIN_AUTO_LIABILITY
    insurance_cargo_passed = cargo_amt >= MIN_CARGO_COVERAGE

    if not insurance_auto_passed:
        msg = (
            f"Auto liability ${auto_amt:,.0f} — minimum ${MIN_AUTO_LIABILITY:,.0f} required"
            if auto_amt else "Auto liability amount not on file"
        )
        violations.append(msg)
    if not insurance_cargo_passed:
        msg = (
            f"Cargo coverage ${cargo_amt:,.0f} — minimum ${MIN_CARGO_COVERAGE:,.0f} required"
            if cargo_amt else "Cargo coverage amount not on file"
        )
        violations.append(msg)

    # ── NDS enrollment (Iron Rule 9) ──────────────────────────────────────────
    nds_enrolled = carrier.nds_enrolled or False
    if not nds_enrolled:
        violations.append("NDS enrollment not confirmed (Iron Rule 9)")

    # ── Risk level ────────────────────────────────────────────────────────────
    overall_passed = len(violations) == 0
    if violations:
        risk_level = "red"
    elif warnings:
        risk_level = "yellow"
    else:
        risk_level = "green"

    return {
        "carrier_mc": carrier.mc_number,
        "carrier_name": carrier.name,
        "authority_age_days": authority_age_days,
        "authority_passed": authority_passed,
        "safety_rating": safety_rating,
        "safety_passed": safety_passed,
        "clearinghouse_passed": clearinghouse_passed,
        "clearinghouse_data_age_days": clearinghouse_data_age_days,
        "coi_expiry": carrier.coi_expiry,
        "coi_valid": coi_valid,
        "coi_days_remaining": coi_days_remaining,
        "insurance_auto_amount": auto_amt,
        "insurance_auto_passed": insurance_auto_passed,
        "insurance_cargo_amount": cargo_amt,
        "insurance_cargo_passed": insurance_cargo_passed,
        "nds_enrolled": nds_enrolled,
        "overall_passed": overall_passed,
        "risk_level": risk_level,
        "violations": violations,
        "warnings": warnings,
    }


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/dashboard")
async def compliance_dashboard(db: AsyncSession = Depends(get_db)):
    """
    Cora's live compliance snapshot for the dashboard.
    At-risk count, expiring COIs, last scan time, suspension alerts.
    """
    now = datetime.utcnow()
    warn_window = now + timedelta(days=COI_YELLOW_DAYS)
    red_window = now + timedelta(days=COI_RED_DAYS)

    result = await db.execute(
        select(Carrier).where(
            Carrier.status.in_([CarrierStatus.ACTIVE, CarrierStatus.TRIAL]),
            Carrier.is_blocked == False,
        )
    )
    carriers = result.scalars().all()

    coi_expiring_soon = [
        c for c in carriers
        if c.coi_expiry and now <= c.coi_expiry <= warn_window
    ]
    coi_expired = [
        c for c in carriers
        if c.coi_expiry and c.coi_expiry < now
    ]
    clearinghouse_stale = [
        c for c in carriers
        if c.clearinghouse_checked_at
        and (now - c.clearinghouse_checked_at).days >= CLEARINGHOUSE_WARN_DAYS
    ]
    missing_insurance = [
        c for c in carriers
        if (c.auto_liability_amount or 0) < MIN_AUTO_LIABILITY
        or (c.cargo_coverage_amount or 0) < MIN_CARGO_COVERAGE
    ]

    # Last scan timestamp
    last_scan = await db.execute(
        select(AutomationLog)
        .where(AutomationLog.action_type.like("cora_%"))
        .order_by(desc(AutomationLog.created_at))
        .limit(1)
    )
    last_scan_row = last_scan.scalar_one_or_none()

    return {
        "snapshot_at": now.isoformat(),
        "total_active_carriers": len(carriers),
        "at_risk": {
            "coi_expired": len(coi_expired),
            "coi_expiring_soon": len(coi_expiring_soon),
            "clearinghouse_stale": len(clearinghouse_stale),
            "missing_insurance": len(missing_insurance),
        },
        "coi_expiring_soon": [
            {
                "mc_number": c.mc_number,
                "name": c.name,
                "coi_expiry": c.coi_expiry,
                "days_remaining": (c.coi_expiry - now).days,
            }
            for c in sorted(coi_expiring_soon, key=lambda x: x.coi_expiry)
        ],
        "last_scan_at": last_scan_row.created_at if last_scan_row else None,
    }


@router.post("/audit/{mc_number}")
async def audit_carrier(
    mc_number: str,
    x_internal_token: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Run a full Cora compliance audit on a single carrier.
    Stores result in compliance_audits table.
    Yellow flags: SMS carrier + Delta summary.
    Red flags: suspend carrier + immediate Delta alert.
    Requires INTERNAL_TOKEN.
    """
    if not verify_internal_token(x_internal_token):
        raise HTTPException(403, "Invalid internal token.")

    result = await db.execute(
        select(Carrier).where(Carrier.mc_number == mc_number)
    )
    carrier = result.scalar_one_or_none()
    if not carrier:
        raise HTTPException(404, f"Carrier MC#{mc_number} not found.")

    audit = run_carrier_audit(carrier)

    # Store audit record
    record = ComplianceAudit(
        carrier_mc=mc_number,
        checked_by="cora",
        authority_age_days=audit["authority_age_days"],
        authority_passed=audit["authority_passed"],
        safety_rating=audit["safety_rating"],
        safety_passed=audit["safety_passed"],
        clearinghouse_passed=audit["clearinghouse_passed"],
        clearinghouse_data_age_days=audit["clearinghouse_data_age_days"],
        coi_expiry=audit["coi_expiry"],
        coi_valid=audit["coi_valid"],
        coi_days_remaining=audit["coi_days_remaining"],
        insurance_auto_amount=audit["insurance_auto_amount"],
        insurance_auto_passed=audit["insurance_auto_passed"],
        insurance_cargo_amount=audit["insurance_cargo_amount"],
        insurance_cargo_passed=audit["insurance_cargo_passed"],
        nds_enrolled=audit["nds_enrolled"],
        overall_passed=audit["overall_passed"],
        risk_level=audit["risk_level"],
        violations=json.dumps(audit["violations"]),
    )
    db.add(record)
    await db.commit()

    # Take action based on risk level
    if audit["risk_level"] == "red":
        # Suspend carrier immediately
        carrier.status = CarrierStatus.SUSPENDED
        await db.commit()
        nova_alert_ceo(
            subject=f"COMPLIANCE VIOLATION — MC#{mc_number} SUSPENDED",
            body=(
                f"Cora found critical compliance violations for {carrier.name} (MC#{mc_number}):\n\n"
                + "\n".join(f"• {v}" for v in audit["violations"])
                + "\n\nCarrier has been suspended automatically. Review and reinstate if resolved."
            ),
        )
        log_automation(
            agent="cora", action_type="cora_audit_red",
            description=f"Critical violations found — carrier suspended: {'; '.join(audit['violations'][:2])}",
            result="suspended", carrier_mc=mc_number, escalated_to_delta=True,
        )

    elif audit["risk_level"] == "yellow":
        # SMS carrier + Delta summary
        if carrier.phone:
            issues = audit["violations"] + audit["warnings"]
            nova_sms(
                carrier.phone,
                f"Hi {carrier.name.split()[0]}, this is Erin with Verlytax Operations. "
                f"We noticed a compliance item that needs attention on your account. "
                f"Please reply or email ops@verlytax.com so we can get this resolved quickly."
            )
        nova_alert_ceo(
            subject=f"Compliance Warning — MC#{mc_number}",
            body=(
                f"Cora flagged warnings for {carrier.name} (MC#{mc_number}):\n\n"
                + "\n".join(f"• {w}" for w in (audit["violations"] + audit["warnings"]))
            ),
        )
        log_automation(
            agent="cora", action_type="cora_audit_yellow",
            description=f"Compliance warnings: {'; '.join((audit['violations'] + audit['warnings'])[:2])}",
            result="warned", carrier_mc=mc_number,
        )
    else:
        log_automation(
            agent="cora", action_type="cora_audit_green",
            description="Full compliance audit passed — all checks green",
            result="passed", carrier_mc=mc_number,
        )

    return {
        "audit_id": record.id,
        "carrier_mc": mc_number,
        "carrier_name": carrier.name,
        "risk_level": audit["risk_level"],
        "overall_passed": audit["overall_passed"],
        "violations": audit["violations"],
        "warnings": audit["warnings"],
        "action_taken": (
            "suspended" if audit["risk_level"] == "red"
            else "warned" if audit["risk_level"] == "yellow"
            else "none"
        ),
    }


@router.get("/audits")
async def list_audits(
    mc_number: Optional[str] = None,
    risk_level: Optional[str] = None,
    limit: int = 25,
    db: AsyncSession = Depends(get_db),
):
    """List compliance audit history with optional filters."""
    q = select(ComplianceAudit).order_by(desc(ComplianceAudit.checked_at))
    if mc_number:
        q = q.where(ComplianceAudit.carrier_mc == mc_number)
    if risk_level:
        q = q.where(ComplianceAudit.risk_level == risk_level)
    q = q.limit(limit)

    result = await db.execute(q)
    audits = result.scalars().all()

    return {
        "total": len(audits),
        "audits": [
            {
                "id": a.id,
                "carrier_mc": a.carrier_mc,
                "checked_by": a.checked_by,
                "checked_at": a.checked_at,
                "risk_level": a.risk_level,
                "overall_passed": a.overall_passed,
                "coi_days_remaining": a.coi_days_remaining,
                "violations": json.loads(a.violations) if a.violations else [],
            }
            for a in audits
        ],
    }


@router.get("/at-risk")
async def at_risk_carriers(db: AsyncSession = Depends(get_db)):
    """
    All active/trial carriers with any open compliance flag.
    Runs audit logic in-memory — does NOT store a new ComplianceAudit record.
    """
    result = await db.execute(
        select(Carrier).where(
            Carrier.status.in_([CarrierStatus.ACTIVE, CarrierStatus.TRIAL]),
            Carrier.is_blocked == False,
        )
    )
    carriers = result.scalars().all()

    at_risk = []
    for c in carriers:
        audit = run_carrier_audit(c)
        if audit["risk_level"] != "green":
            at_risk.append({
                "mc_number": c.mc_number,
                "name": c.name,
                "status": c.status,
                "risk_level": audit["risk_level"],
                "violations": audit["violations"],
                "warnings": audit["warnings"],
                "coi_days_remaining": audit["coi_days_remaining"],
            })

    at_risk.sort(key=lambda x: (0 if x["risk_level"] == "red" else 1, x["mc_number"]))

    return {
        "total": len(at_risk),
        "red": len([c for c in at_risk if c["risk_level"] == "red"]),
        "yellow": len([c for c in at_risk if c["risk_level"] == "yellow"]),
        "carriers": at_risk,
    }


@router.get("/expiring-cois")
async def expiring_cois(
    within_days: int = 60,
    db: AsyncSession = Depends(get_db),
):
    """List carriers with COI expiring within the given number of days (default 60)."""
    now = datetime.utcnow()
    window = now + timedelta(days=within_days)

    result = await db.execute(
        select(Carrier).where(
            Carrier.coi_expiry.isnot(None),
            Carrier.coi_expiry <= window,
            Carrier.status.in_([CarrierStatus.ACTIVE, CarrierStatus.TRIAL]),
            Carrier.is_blocked == False,
        ).order_by(Carrier.coi_expiry)
    )
    carriers = result.scalars().all()

    return {
        "within_days": within_days,
        "total": len(carriers),
        "carriers": [
            {
                "mc_number": c.mc_number,
                "name": c.name,
                "status": c.status,
                "coi_expiry": c.coi_expiry,
                "days_remaining": (c.coi_expiry - now).days,
                "phone": c.phone,
            }
            for c in carriers
        ],
    }
