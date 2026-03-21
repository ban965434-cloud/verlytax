"""
Verlytax OS v4 — Database Layer
All carrier data, loads, billing, and compliance live here.
NEVER store sensitive carrier data in flat files.
"""

import os
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Text, Enum, select
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
import enum

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./verlytax.db")

# Railway provides postgresql:// but asyncpg requires postgresql+asyncpg://
if DATABASE_URL.startswith("postgresql://") or DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1).replace("postgres://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


# ── Enums ────────────────────────────────────────────────────────────────────

class CarrierStatus(str, enum.Enum):
    LEAD = "lead"
    TRIAL = "trial"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CHURNED = "churned"
    BLOCKED = "blocked"

class LoadStatus(str, enum.Enum):
    PENDING = "pending"
    BOOKED = "booked"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    INVOICED = "invoiced"
    PAID = "paid"
    DISPUTED = "disputed"

class SafetyRating(str, enum.Enum):
    SATISFACTORY = "satisfactory"
    NONE = "none"
    CONDITIONAL = "conditional"       # Iron Rule — reject
    UNSATISFACTORY = "unsatisfactory" # Iron Rule — reject


# ── Models ───────────────────────────────────────────────────────────────────

class Carrier(Base):
    __tablename__ = "carriers"

    id = Column(Integer, primary_key=True, index=True)
    mc_number = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    phone = Column(String)
    email = Column(String)
    dot_number = Column(String)
    ein = Column(String)                         # Verified against MC registration
    truck_type = Column(String, default="dry_van")
    equipment_year = Column(Integer)
    vin = Column(String)
    plate = Column(String)

    # Compliance
    authority_granted_date = Column(DateTime)    # Must be 180+ days old (Iron Rule 6/10)
    safety_rating = Column(String, default=SafetyRating.NONE)
    clearinghouse_passed = Column(Boolean, default=False)
    clearinghouse_checked_at = Column(DateTime)
    nds_enrolled = Column(Boolean, default=False) # Iron Rule 9
    coi_expiry = Column(DateTime)
    auto_liability_amount = Column(Float)         # Min $1,000,000
    cargo_coverage_amount = Column(Float)         # Min $100,000

    # Factoring
    factoring_company = Column(String)
    factoring_remittance_address = Column(String)

    # Business
    is_og = Column(Boolean, default=False)           # OG carriers: 8% for life, never increase
    status = Column(String, default=CarrierStatus.LEAD)
    trial_start_date = Column(DateTime)
    active_since = Column(DateTime)
    stripe_customer_id = Column(String)
    stripe_payment_method = Column(String)

    # Trial touchpoint tracking (prevents duplicate SMS / sends)
    sms_day3_sent = Column(Boolean, default=False)
    hellosign_day5_sent = Column(Boolean, default=False)  # Day 5: service agreement via HelloSign
    sms_day7_sent = Column(Boolean, default=False)
    sms_day14_sent = Column(Boolean, default=False)
    sms_day30_sent = Column(Boolean, default=False)

    # Active carrier retention SMS (tracks days since active_since)
    sms_active_day30_sent = Column(Boolean, default=False)  # 30-day feedback ask
    sms_active_day60_sent = Column(Boolean, default=False)  # 60-day review ask

    # Notes (internal dispatch notes, import source, etc.)
    notes = Column(Text)

    # Flags
    is_blocked = Column(Boolean, default=False)
    block_reason = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Load(Base):
    __tablename__ = "loads"

    id = Column(Integer, primary_key=True, index=True)
    carrier_mc = Column(String, index=True)
    broker_name = Column(String)
    broker_contact = Column(String)

    origin_city = Column(String)
    origin_state = Column(String)
    destination_city = Column(String)
    destination_state = Column(String)   # Iron Rule 1: never FL

    total_miles = Column(Float)
    deadhead_miles = Column(Float)       # Iron Rule 3: max 50mi / 25%
    weight_lbs = Column(Float)           # Iron Rule 4: max 48,000 lbs
    rate_total = Column(Float)
    rate_per_mile = Column(Float)        # Iron Rule 2: min $2.51

    pickup_date = Column(DateTime)
    delivery_date = Column(DateTime)
    bol_number = Column(String)
    bol_released = Column(Boolean, default=False)  # Iron Rule 11
    pod_collected = Column(Boolean, default=False)

    status = Column(String, default=LoadStatus.PENDING)

    verlytax_fee = Column(Float)
    fee_collected = Column(Boolean, default=False)
    invoice_sent_at = Column(DateTime)
    invoice_paid_at = Column(DateTime)

    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BlockedBroker(Base):
    """blocked_brokers — Iron Rule 8: permanently blocked brokers."""
    __tablename__ = "blocked_brokers"

    id = Column(Integer, primary_key=True, index=True)
    broker_name = Column(String, nullable=False)
    mc_number = Column(String)
    reason = Column(Text)
    blocked_at = Column(DateTime, default=datetime.utcnow)
    blocked_by = Column(String, default="system")
    dat_filed = Column(Boolean, default=False)


class EscalationLog(Base):
    __tablename__ = "escalation_logs"

    id = Column(Integer, primary_key=True, index=True)
    carrier_mc = Column(String)
    load_id = Column(Integer)
    issue_type = Column(String)
    description = Column(Text)
    amount = Column(Float)
    status = Column(String, default="pending")   # pending / resolved / written_off
    resolved_by = Column(String)                 # "erin" or "delta"
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime)


class AgentMemory(Base):
    """
    Mya's long-term memory engine.
    Every agent reads and writes here — it's the shared intelligence layer.
    Mya synthesizes daily learnings; Delta can manually teach it directly.
    """
    __tablename__ = "agent_memories"

    id = Column(Integer, primary_key=True, index=True)
    agent = Column(String, nullable=False, index=True)        # "mya", "erin", "delta", etc.
    memory_type = Column(String, nullable=False, index=True)  # see types below
    carrier_mc = Column(String, index=True)                   # NULL = global; set = carrier-specific
    subject = Column(String)                                  # short title / label
    content = Column(Text, nullable=False)                    # the full memory text
    importance = Column(Integer, default=3)                   # 1=low, 3=normal, 5=critical
    source = Column(String, default="auto")                   # "auto" (Mya learned it) | "delta" (manually taught)
    recall_count = Column(Integer, default=0)                 # times this memory was pulled into agent context
    last_recalled = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# Memory types:
# "carrier_profile"     — patterns about a specific carrier (payment, lanes, reliability)
# "lane_insight"        — which lanes / regions are profitable or problematic
# "broker_insight"      — broker payment speed, reliability, dispute history
# "interaction_outcome" — what SMS/call approaches worked or failed
# "business_rule"       — custom rules Delta has taught Mya
# "decision_pattern"    — decisions Delta made that Mya should replicate
# "business_insight"    — high-level business intelligence synthesized by Mya


class ComplianceAudit(Base):
    """
    Cora's audit record for each compliance check on a carrier.
    Stores full pass/fail detail for every Iron Rule compliance field.
    """
    __tablename__ = "compliance_audits"

    id = Column(Integer, primary_key=True, index=True)
    carrier_mc = Column(String, nullable=False, index=True)
    checked_by = Column(String, default="cora")               # "cora" | "manual"
    checked_at = Column(DateTime, default=datetime.utcnow)

    # Authority (Iron Rule 6/10)
    authority_age_days = Column(Integer)
    authority_passed = Column(Boolean)

    # Safety rating (Iron Rule 5)
    safety_rating = Column(String)
    safety_passed = Column(Boolean)

    # FMCSA Clearinghouse (Iron Rule 7)
    clearinghouse_passed = Column(Boolean)
    clearinghouse_data_age_days = Column(Integer)             # days since last live check

    # COI / Insurance
    coi_expiry = Column(DateTime)
    coi_valid = Column(Boolean)
    coi_days_remaining = Column(Integer)
    insurance_auto_amount = Column(Float)
    insurance_auto_passed = Column(Boolean)                   # must be >= $1,000,000
    insurance_cargo_amount = Column(Float)
    insurance_cargo_passed = Column(Boolean)                  # must be >= $100,000

    # NDS (Iron Rule 9)
    nds_enrolled = Column(Boolean)

    # Result
    overall_passed = Column(Boolean, default=False)
    risk_level = Column(String, default="green")              # "green" | "yellow" | "red"
    violations = Column(Text)                                 # JSON list of violation strings
    notes = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)


class SupportTicket(Base):
    """
    Zara's support ticket system.
    Every carrier question, billing issue, or complaint gets a ticket.
    """
    __tablename__ = "support_tickets"

    id = Column(Integer, primary_key=True, index=True)
    ticket_number = Column(String, unique=True, nullable=False, index=True)  # "TKT-0001"
    carrier_mc = Column(String, index=True)
    phone = Column(String)                                    # carrier phone for SMS replies

    category = Column(String, nullable=False)                 # billing | load_issue | compliance | account | general
    subject = Column(String, nullable=False)
    description = Column(Text, nullable=False)

    status = Column(String, default="open")                   # open | in_progress | resolved | escalated
    priority = Column(String, default="normal")               # low | normal | high | urgent
    assigned_to = Column(String, default="zara")              # zara | erin | delta

    zara_response = Column(Text)                              # Zara's drafted/sent reply
    resolution = Column(Text)                                 # final resolution note
    escalation_reason = Column(Text)

    # Voice escalation — Retell outbound call tracking
    voice_call_id = Column(String, index=True)                # Retell call ID when voice-escalated
    voice_escalated_at = Column(DateTime)
    voice_transcript = Column(Text)                           # call transcript from Retell webhook

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    resolved_at = Column(DateTime)


class AutomationLog(Base):
    """Audit trail for every autonomous action taken by Brain, Erin, or any agent."""
    __tablename__ = "automation_logs"

    id = Column(Integer, primary_key=True, index=True)
    agent = Column(String, nullable=False)            # "brain", "erin", "megan", "receptionist", etc.
    action_type = Column(String, nullable=False)      # "coi_expiry_sms", "overdue_load_alert", etc.
    carrier_mc = Column(String, index=True)
    load_id = Column(Integer)
    description = Column(Text)
    result = Column(String)                           # "sent", "skipped", "failed", "escalated"
    escalated_to_delta = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class BrokerProfile(Base):
    """
    Broker knowledge library — positive database of brokers Verlytax works WITH.
    NOT the blocked broker list (that's BlockedBroker / Iron Rule 8).
    Mya updates counters + payment days daily via mya_learn().
    """
    __tablename__ = "broker_profiles"

    id = Column(Integer, primary_key=True, index=True)
    broker_name = Column(String, nullable=False, index=True)
    mc_number = Column(String, unique=True, index=True, nullable=False)
    contact_name = Column(String)
    contact_phone = Column(String)
    contact_email = Column(String)
    lanes_covered = Column(Text)              # e.g. "TX→CA, OH→GA, IL→TX"
    avg_payment_days = Column(Float)          # average days delivery→payment
    reliability_rating = Column(Integer, default=3)  # 1=worst, 5=best; Delta sets this
    total_loads_booked = Column(Integer, default=0)  # Mya increments daily
    total_disputes = Column(Integer, default=0)       # Mya increments on DISPUTED loads
    notes = Column(Text)
    is_preferred = Column(Boolean, default=False)     # Delta marks top brokers preferred

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AutomationRule(Base):
    """Governance layer — Delta can disable any autonomous automation without a code deploy."""
    __tablename__ = "automation_rules"

    id = Column(Integer, primary_key=True, index=True)
    rule_key = Column(String, unique=True, nullable=False, index=True)
    description = Column(String, nullable=False)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# Default rules seeded on first startup
DEFAULT_AUTOMATION_RULES = [
    ("annual_fmcsa_recheck",  "Annual FMCSA Clearinghouse re-check on all active carriers"),
    ("coi_expiry_check",      "Daily COI expiry warning — alerts Delta + SMS carrier when COI within 30 days"),
    ("testimonial_sms",       "Retention SMS at Day 30 and Day 60 of active status"),
    ("overdue_load_scan",     "Daily scan for loads in-transit past delivery date by 24+ hours"),
    ("stale_lead_scan",       "Daily scan for leads with no activity in 14+ days — alerts Delta"),
    ("no_load_carrier_scan",  "Daily scan for active carriers with no loads in 14+ days — Erin check-in SMS"),
    ("mya_learn",             "Daily 6 AM — Mya synthesizes load/dispute data into AgentMemory learnings"),
    ("cora_compliance_scan",  "Weekly Monday 7:30 AM — Cora audits all active carriers for compliance violations"),
    ("support_ticket_sweep",  "Daily 9:30 AM — Zara follows up on open tickets >24h; auto-escalates tickets >48h"),
]


# ── Session dependency ────────────────────────────────────────────────────────

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed default automation rules (idempotent — skips if already exist)
    async with AsyncSessionLocal() as session:
        for rule_key, description in DEFAULT_AUTOMATION_RULES:
            existing = await session.execute(
                select(AutomationRule).where(AutomationRule.rule_key == rule_key)
            )
            if not existing.scalar_one_or_none():
                session.add(AutomationRule(rule_key=rule_key, description=description))
        await session.commit()
