"""
Verlytax OS v4 — Carrier Database Engine
Bulk import, carrier list management, search, and movement tracking.
"""

import csv
import io
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from app.db import get_db, Carrier, CarrierStatus

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class CarrierImportRow(BaseModel):
    mc_number: str
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    dot_number: Optional[str] = None
    truck_type: Optional[str] = "dry_van"
    factoring_company: Optional[str] = None
    state: Optional[str] = None
    notes: Optional[str] = None


class BulkImportResult(BaseModel):
    imported: int
    skipped: int
    errors: list[str]


# ── Bulk CSV Import ────────────────────────────────────────────────────────────

@router.post("/import", response_model=BulkImportResult)
async def bulk_import_carriers(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Bulk import carriers from CSV. Auto-populates verlytax.db carriers table.

    Required CSV columns: mc_number, name
    Optional: phone, email, dot_number, truck_type, factoring_company, state, notes

    Skips duplicates (by MC#). Returns count of imported, skipped, and any errors.
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(400, "File must be a .csv")

    contents = await file.read()
    text = contents.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))

    imported = 0
    skipped = 0
    errors = []

    for i, row in enumerate(reader, start=2):  # row 1 = header
        mc = (row.get("mc_number") or row.get("MC#") or row.get("mc") or "").strip()
        name = (row.get("name") or row.get("Name") or row.get("company") or "").strip()

        if not mc or not name:
            errors.append(f"Row {i}: missing mc_number or name — skipped")
            continue

        # Deduplicate
        existing = await db.execute(select(Carrier).where(Carrier.mc_number == mc))
        if existing.scalar_one_or_none():
            skipped += 1
            continue

        try:
            carrier = Carrier(
                mc_number=mc,
                name=name,
                phone=(row.get("phone") or "").strip() or None,
                email=(row.get("email") or "").strip() or None,
                dot_number=(row.get("dot_number") or row.get("DOT#") or "").strip() or None,
                truck_type=(row.get("truck_type") or "dry_van").strip(),
                factoring_company=(row.get("factoring_company") or "").strip() or None,
                notes=(row.get("notes") or "").strip() or None,
                status=CarrierStatus.LEAD,
            )
            db.add(carrier)
            imported += 1
        except Exception as e:
            errors.append(f"Row {i} (MC#{mc}): {str(e)}")

    await db.commit()
    return BulkImportResult(imported=imported, skipped=skipped, errors=errors)


# ── Carrier List + Search ──────────────────────────────────────────────────────

@router.get("/list")
async def list_carriers(
    status: Optional[str] = Query(None, description="Filter by status: lead/trial/active/suspended"),
    search: Optional[str] = Query(None, description="Search by name, MC#, phone, or email"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
):
    """
    List all carriers in verlytax.db with optional filters.
    Use `status` to filter by pipeline stage. Use `search` for name/MC lookup.
    """
    query = select(Carrier).where(Carrier.is_blocked == False)

    if status:
        try:
            status_enum = CarrierStatus(status.lower())
            query = query.where(Carrier.status == status_enum)
        except ValueError:
            raise HTTPException(400, f"Invalid status: {status}. Use: lead, trial, active, suspended, inactive")

    if search:
        term = f"%{search}%"
        query = query.where(
            or_(
                Carrier.name.ilike(term),
                Carrier.mc_number.ilike(term),
                Carrier.phone.ilike(term),
                Carrier.email.ilike(term),
            )
        )

    query = query.order_by(Carrier.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    carriers = result.scalars().all()

    return {
        "total": len(carriers),
        "offset": offset,
        "carriers": [
            {
                "id": c.id,
                "mc_number": c.mc_number,
                "name": c.name,
                "phone": c.phone,
                "email": c.email,
                "truck_type": c.truck_type,
                "status": c.status,
                "factoring_company": c.factoring_company,
                "active_since": c.active_since,
                "trial_start_date": c.trial_start_date,
                "safety_rating": c.safety_rating,
                "nds_enrolled": c.nds_enrolled,
                "clearinghouse_passed": c.clearinghouse_passed,
                "created_at": c.created_at,
            }
            for c in carriers
        ],
    }


@router.get("/stats")
async def carrier_pipeline_stats(db: AsyncSession = Depends(get_db)):
    """
    Carrier pipeline snapshot — counts by status.
    Used by the dashboard to populate stat cards.
    """
    counts = {}
    for status in CarrierStatus:
        result = await db.execute(
            select(Carrier).where(
                Carrier.status == status,
                Carrier.is_blocked == False,
            )
        )
        counts[status.value] = len(result.scalars().all())

    return {
        "pipeline": counts,
        "total_active": counts.get("active", 0),
        "total_trial": counts.get("trial", 0),
        "total_leads": counts.get("lead", 0),
    }


@router.get("/export/csv")
async def export_carriers_csv(
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Export carrier list as CSV for offline use, LinkedIn outreach lists, etc.
    """
    from fastapi.responses import StreamingResponse

    query = select(Carrier).where(Carrier.is_blocked == False)
    if status:
        try:
            query = query.where(Carrier.status == CarrierStatus(status.lower()))
        except ValueError:
            raise HTTPException(400, f"Invalid status: {status}")

    result = await db.execute(query)
    carriers = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "mc_number", "name", "phone", "email", "dot_number",
        "truck_type", "status", "factoring_company",
        "safety_rating", "nds_enrolled", "active_since", "created_at"
    ])
    for c in carriers:
        writer.writerow([
            c.mc_number, c.name, c.phone, c.email, c.dot_number,
            c.truck_type, c.status, c.factoring_company,
            c.safety_rating, c.nds_enrolled, c.active_since, c.created_at
        ])

    output.seek(0)
    filename = f"verlytax_carriers_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
