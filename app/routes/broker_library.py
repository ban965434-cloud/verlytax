"""
Verlytax OS v4 — Broker Library
Knowledge base of brokers Verlytax works WITH: lanes, payment speed, reliability.
NOT the blocked broker list — that's Iron Rule 8 / BlockedBroker table.
"""

import csv
import io
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from app.db import get_db, BrokerProfile

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class BrokerCreate(BaseModel):
    broker_name: str
    mc_number: str
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    lanes_covered: Optional[str] = None
    avg_payment_days: Optional[float] = None
    reliability_rating: Optional[int] = Field(default=3, ge=1, le=5)
    notes: Optional[str] = None
    is_preferred: bool = False


class BrokerUpdate(BaseModel):
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    lanes_covered: Optional[str] = None
    avg_payment_days: Optional[float] = None
    reliability_rating: Optional[int] = Field(default=None, ge=1, le=5)
    notes: Optional[str] = None
    is_preferred: Optional[bool] = None


# ── Add Broker ────────────────────────────────────────────────────────────────

@router.post("/add")
async def add_broker(data: BrokerCreate, db: AsyncSession = Depends(get_db)):
    """
    Add a broker to the Verlytax broker library.
    Deduplicated by MC number — skips if already exists.
    """
    existing = await db.execute(
        select(BrokerProfile).where(BrokerProfile.mc_number == data.mc_number)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"Broker MC#{data.mc_number} already exists. Use PUT /brokers/{data.mc_number}/update.")

    broker = BrokerProfile(
        broker_name=data.broker_name,
        mc_number=data.mc_number,
        contact_name=data.contact_name,
        contact_phone=data.contact_phone,
        contact_email=data.contact_email,
        lanes_covered=data.lanes_covered,
        avg_payment_days=data.avg_payment_days,
        reliability_rating=data.reliability_rating or 3,
        notes=data.notes,
        is_preferred=data.is_preferred,
    )
    db.add(broker)
    await db.commit()
    await db.refresh(broker)

    return {
        "status": "added",
        "mc_number": broker.mc_number,
        "broker_name": broker.broker_name,
    }


# ── Broker List + Search ──────────────────────────────────────────────────────

@router.get("/list")
async def list_brokers(
    search: Optional[str] = Query(None, description="Search by name, MC#, or contact name"),
    min_reliability: Optional[int] = Query(None, ge=1, le=5, description="Minimum reliability rating"),
    is_preferred: Optional[bool] = Query(None, description="Filter to preferred brokers only"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
):
    """
    List all brokers in the library with optional filters.
    Mya updates reliability stats and payment days daily.
    """
    query = select(BrokerProfile)

    if search:
        term = f"%{search}%"
        query = query.where(
            or_(
                BrokerProfile.broker_name.ilike(term),
                BrokerProfile.mc_number.ilike(term),
                BrokerProfile.contact_name.ilike(term),
            )
        )

    if min_reliability is not None:
        query = query.where(BrokerProfile.reliability_rating >= min_reliability)

    if is_preferred is not None:
        query = query.where(BrokerProfile.is_preferred == is_preferred)

    query = query.order_by(BrokerProfile.reliability_rating.desc(), BrokerProfile.broker_name).offset(offset).limit(limit)
    result = await db.execute(query)
    brokers = result.scalars().all()

    return {
        "total": len(brokers),
        "offset": offset,
        "brokers": [
            {
                "mc_number": b.mc_number,
                "broker_name": b.broker_name,
                "contact_name": b.contact_name,
                "contact_phone": b.contact_phone,
                "contact_email": b.contact_email,
                "lanes_covered": b.lanes_covered,
                "avg_payment_days": b.avg_payment_days,
                "reliability_rating": b.reliability_rating,
                "total_loads_booked": b.total_loads_booked,
                "total_disputes": b.total_disputes,
                "is_preferred": b.is_preferred,
                "notes": b.notes,
                "created_at": b.created_at,
            }
            for b in brokers
        ],
    }


# ── Single Broker ─────────────────────────────────────────────────────────────

@router.get("/{mc_number}")
async def get_broker(mc_number: str, db: AsyncSession = Depends(get_db)):
    """Full broker profile by MC number."""
    result = await db.execute(
        select(BrokerProfile).where(BrokerProfile.mc_number == mc_number)
    )
    broker = result.scalar_one_or_none()
    if not broker:
        raise HTTPException(404, f"Broker MC#{mc_number} not found in library.")

    return {
        "mc_number": broker.mc_number,
        "broker_name": broker.broker_name,
        "contact_name": broker.contact_name,
        "contact_phone": broker.contact_phone,
        "contact_email": broker.contact_email,
        "lanes_covered": broker.lanes_covered,
        "avg_payment_days": broker.avg_payment_days,
        "reliability_rating": broker.reliability_rating,
        "total_loads_booked": broker.total_loads_booked,
        "total_disputes": broker.total_disputes,
        "is_preferred": broker.is_preferred,
        "notes": broker.notes,
        "created_at": broker.created_at,
        "updated_at": broker.updated_at,
    }


# ── Update Broker ─────────────────────────────────────────────────────────────

@router.put("/{mc_number}/update")
async def update_broker(
    mc_number: str,
    data: BrokerUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update any field on a broker profile."""
    result = await db.execute(
        select(BrokerProfile).where(BrokerProfile.mc_number == mc_number)
    )
    broker = result.scalar_one_or_none()
    if not broker:
        raise HTTPException(404, f"Broker MC#{mc_number} not found.")

    if data.contact_name is not None:
        broker.contact_name = data.contact_name
    if data.contact_phone is not None:
        broker.contact_phone = data.contact_phone
    if data.contact_email is not None:
        broker.contact_email = data.contact_email
    if data.lanes_covered is not None:
        broker.lanes_covered = data.lanes_covered
    if data.avg_payment_days is not None:
        broker.avg_payment_days = data.avg_payment_days
    if data.reliability_rating is not None:
        broker.reliability_rating = data.reliability_rating
    if data.notes is not None:
        broker.notes = data.notes
    if data.is_preferred is not None:
        broker.is_preferred = data.is_preferred

    broker.updated_at = datetime.utcnow()
    await db.commit()

    return {"status": "updated", "mc_number": mc_number}


# ── CSV Export ────────────────────────────────────────────────────────────────

@router.get("/export/csv")
async def export_brokers_csv(db: AsyncSession = Depends(get_db)):
    """Export full broker library as CSV."""
    result = await db.execute(select(BrokerProfile).order_by(BrokerProfile.broker_name))
    brokers = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "mc_number", "broker_name", "contact_name", "contact_phone", "contact_email",
        "lanes_covered", "avg_payment_days", "reliability_rating",
        "total_loads_booked", "total_disputes", "is_preferred", "notes", "created_at"
    ])
    for b in brokers:
        writer.writerow([
            b.mc_number, b.broker_name, b.contact_name, b.contact_phone, b.contact_email,
            b.lanes_covered, b.avg_payment_days, b.reliability_rating,
            b.total_loads_booked, b.total_disputes, b.is_preferred, b.notes, b.created_at
        ])

    output.seek(0)
    filename = f"verlytax_brokers_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
