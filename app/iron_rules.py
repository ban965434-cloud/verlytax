"""
Verlytax OS v4 — Iron Rules Enforcer
11 non-negotiable rules. No bypasses. No exceptions. Ever.
The only person who can modify an Iron Rule is Delta.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional


# ── Thresholds (source of truth) ─────────────────────────────────────────────

MIN_RPM = 2.51
COUNTER_RPM = 2.74      # Below this: counter-offer required before accepting
ACCEPT_RPM = 2.75       # At or above: acceptable to book
EXCELLENT_RPM = 3.00    # Prioritize

MAX_DEADHEAD_MILES = 50
MAX_DEADHEAD_PCT = 0.25
MAX_WEIGHT_LBS = 48_000
MIN_AUTHORITY_DAYS = 180

BLOCKED_STATE = "FL"    # Iron Rule 1


@dataclass
class RuleViolation:
    rule_number: int
    rule_name: str
    message: str
    action: str = "REJECT"   # REJECT or COUNTER


@dataclass
class LoadCheckResult:
    passed: bool
    violations: list[RuleViolation]

    @property
    def rejection_reason(self) -> Optional[str]:
        rejects = [v for v in self.violations if v.action == "REJECT"]
        if rejects:
            return rejects[0].message
        return None

    @property
    def requires_counter(self) -> bool:
        return any(v.action == "COUNTER" for v in self.violations)


@dataclass
class CarrierCheckResult:
    passed: bool
    violations: list[RuleViolation]


# ── Load Iron Rules ───────────────────────────────────────────────────────────

def check_load(
    origin_state: str,
    destination_state: str,
    rate_per_mile: float,
    deadhead_miles: float,
    total_miles: float,
    weight_lbs: float,
) -> LoadCheckResult:
    """
    Run all load-level Iron Rules before booking.
    Returns a LoadCheckResult — check .passed before proceeding.
    """
    violations: list[RuleViolation] = []

    # Rule 1 — No Florida loads (pickup OR delivery)
    if origin_state.upper() == BLOCKED_STATE or destination_state.upper() == BLOCKED_STATE:
        violations.append(RuleViolation(
            rule_number=1,
            rule_name="NO FLORIDA LOADS",
            message=f"Florida loads are permanently excluded. State: {origin_state} → {destination_state}",
            action="REJECT",
        ))

    # Rule 2 — Min RPM $2.51
    if rate_per_mile < MIN_RPM:
        violations.append(RuleViolation(
            rule_number=2,
            rule_name="MIN RPM $2.51",
            message=f"RPM ${rate_per_mile:.2f} is below the hard floor of ${MIN_RPM:.2f}.",
            action="REJECT",
        ))
    elif rate_per_mile <= COUNTER_RPM:
        violations.append(RuleViolation(
            rule_number=2,
            rule_name="MIN RPM $2.51 — COUNTER REQUIRED",
            message=f"RPM ${rate_per_mile:.2f} is in counter-offer zone (${MIN_RPM}–${COUNTER_RPM}). Negotiate up before accepting.",
            action="COUNTER",
        ))

    # Rule 3 — Max deadhead 50 miles / 25%
    if total_miles > 0:
        deadhead_pct = deadhead_miles / total_miles
    else:
        deadhead_pct = 0.0

    if deadhead_miles > MAX_DEADHEAD_MILES or deadhead_pct > MAX_DEADHEAD_PCT:
        violations.append(RuleViolation(
            rule_number=3,
            rule_name="MAX DEADHEAD 50mi/25%",
            message=(
                f"Deadhead {deadhead_miles:.0f}mi ({deadhead_pct*100:.1f}%) exceeds limits "
                f"(max {MAX_DEADHEAD_MILES}mi / {MAX_DEADHEAD_PCT*100:.0f}%)."
            ),
            action="REJECT",
        ))

    # Rule 4 — Max weight 48,000 lbs
    if weight_lbs > MAX_WEIGHT_LBS:
        violations.append(RuleViolation(
            rule_number=4,
            rule_name="MAX WEIGHT 48,000 lbs",
            message=f"Load weight {weight_lbs:,.0f} lbs exceeds max {MAX_WEIGHT_LBS:,} lbs.",
            action="REJECT",
        ))

    hard_rejects = [v for v in violations if v.action == "REJECT"]
    return LoadCheckResult(passed=len(hard_rejects) == 0, violations=violations)


# ── Carrier Iron Rules ────────────────────────────────────────────────────────

def check_carrier(
    safety_rating: str,
    authority_granted_date: Optional[datetime],
    clearinghouse_passed: bool,
    nds_enrolled: bool,
    is_blocked: bool,
) -> CarrierCheckResult:
    """
    Run all carrier-level Iron Rules before onboarding or dispatching.
    """
    violations: list[RuleViolation] = []

    # Rule 5 — No unsatisfactory / conditional safety ratings
    if safety_rating.lower() in ("unsatisfactory", "conditional"):
        violations.append(RuleViolation(
            rule_number=5,
            rule_name="NO UNSATISFACTORY/CONDITIONAL SAFETY RATINGS",
            message=f"Carrier safety rating '{safety_rating}' is not acceptable.",
            action="REJECT",
        ))

    # Rule 6 & 10 — Authority age 180+ days
    if authority_granted_date is None:
        violations.append(RuleViolation(
            rule_number=6,
            rule_name="AUTHORITY AGE 180+ DAYS",
            message="Authority granted date not on file. Cannot verify 180-day minimum.",
            action="REJECT",
        ))
    else:
        age_days = (datetime.utcnow() - authority_granted_date).days
        if age_days < MIN_AUTHORITY_DAYS:
            violations.append(RuleViolation(
                rule_number=6,
                rule_name="AUTHORITY AGE 180+ DAYS",
                message=f"Carrier authority is only {age_days} days old. Minimum is {MIN_AUTHORITY_DAYS} days.",
                action="REJECT",
            ))

    # Rule 7 — Failed FMCSA Clearinghouse
    if not clearinghouse_passed:
        violations.append(RuleViolation(
            rule_number=7,
            rule_name="FAILED FMCSA CLEARINGHOUSE",
            message="Carrier failed or has not completed FMCSA Clearinghouse check.",
            action="REJECT",
        ))

    # Rule 9 — NDS enrollment before Day 1 load
    if not nds_enrolled:
        violations.append(RuleViolation(
            rule_number=9,
            rule_name="NDS ENROLLMENT BEFORE DAY 1 LOAD",
            message="Carrier must complete NDS enrollment ($100/yr) before first dispatch.",
            action="REJECT",
        ))

    # Rule 8 — Blocked carrier (mapped from memory_brokers pattern)
    if is_blocked:
        violations.append(RuleViolation(
            rule_number=8,
            rule_name="BLOCKED CARRIER",
            message="Carrier is permanently blocked in Verlytax system.",
            action="REJECT",
        ))

    return CarrierCheckResult(passed=len(violations) == 0, violations=violations)


# ── BOL Release Guard (Rule 11) ───────────────────────────────────────────────

def can_release_bol(delivery_confirmed: bool) -> bool:
    """Iron Rule 11: Never release BOL before delivery confirmed."""
    return delivery_confirmed


def get_rpm_tier(rpm: float) -> str:
    if rpm < MIN_RPM:
        return "HARD_REJECT"
    elif rpm <= COUNTER_RPM:
        return "COUNTER_REQUIRED"
    elif rpm < EXCELLENT_RPM:
        return "ACCEPTABLE"
    else:
        return "EXCELLENT"
