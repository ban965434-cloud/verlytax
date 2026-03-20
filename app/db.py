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

    # Trial touchpoint tracking (prevents duplicate SMS)
    sms_day3_sent = Column(Boolean, default=False)
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
