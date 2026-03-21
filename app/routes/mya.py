"""
Verlytax OS v4 — Mya: Intelligence Engine & Memory Agent
Mya learns from every load, dispute, and carrier interaction.
She stores insights, recalls context for other agents, and teaches herself.
"""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.db import get_db, AgentMemory, AutomationLog, Carrier, Load, EscalationLog, CarrierStatus
from app.services import verify_internal_token, store_memory, run_agent

router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────────────────

class MemoryCreate(BaseModel):
    memory_type: str       # carrier_profile | lane_insight | broker_insight | business_rule | decision_pattern | business_insight
    content: str
    carrier_mc: Optional[str] = None
    subject: Optional[str] = None
    importance: int = 3    # 1–5


class MemoryUpdate(BaseModel):
    content: Optional[str] = None
    importance: Optional[int] = None
    subject: Optional[str] = None


# ── Memory CRUD ────────────────────────────────────────────────────────────────

@router.get("/memory")
async def list_memories(
    carrier_mc: Optional[str] = None,
    memory_type: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 25,
    db: AsyncSession = Depends(get_db),
):
    """
    List Mya's stored memories. Filter by carrier_mc, memory_type, or source.
    Used by the dashboard Memory Browser and by agents that need context injection.
    """
    q = select(AgentMemory).order_by(
        desc(AgentMemory.importance),
        desc(AgentMemory.created_at),
    )
    if carrier_mc:
        q = q.where(AgentMemory.carrier_mc == carrier_mc)
    if memory_type:
        q = q.where(AgentMemory.memory_type == memory_type)
    if source:
        q = q.where(AgentMemory.source == source)
    q = q.limit(limit)

    result = await db.execute(q)
    memories = result.scalars().all()

    return {
        "total": len(memories),
        "memories": [
            {
                "id": m.id,
                "agent": m.agent,
                "memory_type": m.memory_type,
                "carrier_mc": m.carrier_mc,
                "subject": m.subject,
                "content": m.content,
                "importance": m.importance,
                "source": m.source,
                "recall_count": m.recall_count,
                "last_recalled": m.last_recalled,
                "created_at": m.created_at,
            }
            for m in memories
        ],
    }


@router.get("/memory/carrier/{mc_number}")
async def carrier_memory(mc_number: str, db: AsyncSession = Depends(get_db)):
    """
    Pull the full memory profile for a specific carrier.
    Erin uses this before responding to any carrier SMS.
    """
    result = await db.execute(
        select(AgentMemory)
        .where(
            (AgentMemory.carrier_mc == mc_number) | (AgentMemory.carrier_mc.is_(None))
        )
        .order_by(desc(AgentMemory.importance), desc(AgentMemory.created_at))
        .limit(15)
    )
    memories = result.scalars().all()

    # Bump recall counts
    for m in memories:
        m.recall_count = (m.recall_count or 0) + 1
        m.last_recalled = datetime.utcnow()
    await db.commit()

    return {
        "carrier_mc": mc_number,
        "memory_count": len(memories),
        "memories": [
            {
                "id": m.id,
                "memory_type": m.memory_type,
                "subject": m.subject,
                "content": m.content,
                "importance": m.importance,
                "source": m.source,
                "created_at": m.created_at,
            }
            for m in memories
        ],
    }


@router.post("/memory")
async def create_memory(
    data: MemoryCreate,
    x_internal_token: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Delta teaches Mya something. Source is set to 'delta' so the system
    knows this is intentional human-provided knowledge.
    Requires INTERNAL_TOKEN.
    """
    if not verify_internal_token(x_internal_token):
        raise HTTPException(403, "Invalid internal token.")

    valid_types = {
        "carrier_profile", "lane_insight", "broker_insight",
        "interaction_outcome", "business_rule", "decision_pattern", "business_insight",
    }
    if data.memory_type not in valid_types:
        raise HTTPException(400, f"memory_type must be one of: {', '.join(sorted(valid_types))}")

    if data.importance < 1 or data.importance > 5:
        raise HTTPException(400, "importance must be 1–5.")

    memory = AgentMemory(
        agent="delta",
        memory_type=data.memory_type,
        carrier_mc=data.carrier_mc,
        subject=data.subject,
        content=data.content,
        importance=data.importance,
        source="delta",
    )
    db.add(memory)
    await db.commit()

    return {
        "status": "stored",
        "id": memory.id,
        "memory_type": data.memory_type,
        "importance": data.importance,
        "note": "Mya will use this in all future agent responses.",
    }


@router.patch("/memory/{memory_id}")
async def update_memory(
    memory_id: int,
    data: MemoryUpdate,
    x_internal_token: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing memory. Requires INTERNAL_TOKEN."""
    if not verify_internal_token(x_internal_token):
        raise HTTPException(403, "Invalid internal token.")

    memory = await db.get(AgentMemory, memory_id)
    if not memory:
        raise HTTPException(404, f"Memory #{memory_id} not found.")

    if data.content is not None:
        memory.content = data.content
    if data.importance is not None:
        if data.importance < 1 or data.importance > 5:
            raise HTTPException(400, "importance must be 1–5.")
        memory.importance = data.importance
    if data.subject is not None:
        memory.subject = data.subject

    memory.updated_at = datetime.utcnow()
    await db.commit()

    return {"status": "updated", "id": memory_id}


@router.delete("/memory/{memory_id}")
async def forget_memory(
    memory_id: int,
    x_internal_token: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a memory (Mya forgets it). Requires INTERNAL_TOKEN.
    Delta-sourced memories are deletable — Mya-sourced memories should rarely be deleted.
    """
    if not verify_internal_token(x_internal_token):
        raise HTTPException(403, "Invalid internal token.")

    memory = await db.get(AgentMemory, memory_id)
    if not memory:
        raise HTTPException(404, f"Memory #{memory_id} not found.")

    await db.delete(memory)
    await db.commit()

    return {"status": "forgotten", "id": memory_id}


# ── Intelligence: Mya's Live Insights ─────────────────────────────────────────

@router.get("/insights")
async def mya_insights(db: AsyncSession = Depends(get_db)):
    """
    Mya's real-time intelligence snapshot:
    - Carrier pipeline health
    - Revenue trends
    - Memory stats
    - Automation health
    """
    now = datetime.utcnow()
    from datetime import timedelta
    from sqlalchemy import func

    # Carrier pipeline counts
    result = await db.execute(select(Carrier))
    all_carriers = result.scalars().all()
    by_status = {}
    for c in all_carriers:
        s = str(c.status)
        by_status[s] = by_status.get(s, 0) + 1

    # Load stats last 30 days
    cutoff = now - timedelta(days=30)
    loads_result = await db.execute(select(Load).where(Load.created_at >= cutoff))
    recent_loads = loads_result.scalars().all()
    total_revenue = sum(l.rate_total or 0 for l in recent_loads if l.status in ("delivered", "paid"))
    avg_rpm = (
        sum(l.rate_per_mile or 0 for l in recent_loads if l.rate_per_mile) / max(len(recent_loads), 1)
    )

    # Memory stats
    mem_result = await db.execute(select(AgentMemory))
    all_memories = mem_result.scalars().all()
    memory_stats = {
        "total": len(all_memories),
        "by_type": {},
        "by_source": {"auto": 0, "delta": 0},
        "top_importance": len([m for m in all_memories if m.importance >= 4]),
    }
    for m in all_memories:
        memory_stats["by_type"][m.memory_type] = memory_stats["by_type"].get(m.memory_type, 0) + 1
        if m.source in memory_stats["by_source"]:
            memory_stats["by_source"][m.source] += 1

    # Recent automation log entries
    log_result = await db.execute(
        select(AutomationLog)
        .order_by(AutomationLog.created_at.desc())
        .limit(5)
    )
    recent_actions = log_result.scalars().all()

    return {
        "snapshot_at": now.isoformat(),
        "carrier_pipeline": by_status,
        "loads_last_30d": {
            "count": len(recent_loads),
            "total_revenue": round(total_revenue, 2),
            "avg_rpm": round(avg_rpm, 2),
        },
        "memory": memory_stats,
        "recent_actions": [
            {
                "agent": a.agent,
                "action_type": a.action_type,
                "result": a.result,
                "created_at": a.created_at,
            }
            for a in recent_actions
        ],
    }
