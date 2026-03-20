"""
Verlytax OS v4 — Database Layer
All carrier data, loads, billing, and compliance live here.
NEVER store sensitive carrier data in flat files.
"""

import os
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Text, Enum
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
    INACTIVE = "inactive"
    BLOCKED = "blocked"

class LoadStatus(str, enum.Enum):
    SEARCHING = "searching"
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

    status = Column(String, default=LoadStatus.SEARCHING)

    verlytax_fee = Column(Float)
    fee_collected = Column(Boolean, default=False)
    invoice_sent_at = Column(DateTime)
    invoice_paid_at = Column(DateTime)

    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BlockedBroker(Base):
    """memory_brokers — Iron Rule 8: permanently blocked brokers."""
    __tablename__ = "memory_brokers"

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
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime)


# ── Session dependency ────────────────────────────────────────────────────────

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
