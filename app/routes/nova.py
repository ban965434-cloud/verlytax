"""
Verlytax OS v4 — Nova Routes
Nova Command Center: test scenarios, CEO shadow log, training SOP export
"""

import os
import asyncio
from datetime import datetime
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Optional

from app.services import nova_respond, log_automation, store_memory, verify_internal_token

router = APIRouter()

AIOS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "VERLYTAX_AIOS")
TRAINING_LOG_PATH = os.path.join(AIOS_DIR, "SOPs", "SOP_TRAINING_LOG.md")


class NovaTestRequest(BaseModel):
    message: str
    scenario: Optional[str] = None   # e.g. "STATUS command", "HALT ALL flow"
    label: Optional[str] = None      # human-readable label for the log


def _append_training_log(scenario: str, message: str, response: str) -> None:
    """Append a test scenario result to SOP_TRAINING_LOG.md."""
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    entry = (
        f"\n---\n"
        f"## Scenario: {scenario}\n"
        f"**Timestamp:** {timestamp}\n\n"
        f"**Delta input:** {message}\n\n"
        f"**Nova response:**\n{response}\n"
    )
    try:
        # Create file with header if it doesn't exist
        if not os.path.exists(TRAINING_LOG_PATH):
            header = (
                "# SOP_TRAINING_LOG.md\n"
                "Verlytax OS v4 — Nova & CEO Agent Training Scenarios\n"
                "Auto-generated. Every test run is recorded here.\n"
                "All agents can read this log as a live SOP reference.\n\n"
            )
            with open(TRAINING_LOG_PATH, "w") as f:
                f.write(header)
        with open(TRAINING_LOG_PATH, "a") as f:
            f.write(entry)
    except Exception:
        pass  # Never let log writing crash the test endpoint


# ── POST /nova/test ────────────────────────────────────────────────────────────

@router.post("/test")
async def nova_test(
    body: NovaTestRequest,
    x_internal_token: str = Header(None),
):
    """
    Test Nova with any message. No Twilio needed.
    - Runs nova_respond() with the message
    - Logs to AutomationLog (audit trail)
    - Logs to AgentMemory as CEO shadow observation
    - If scenario is named, appends result to SOP_TRAINING_LOG.md
    Requires INTERNAL_TOKEN header.
    """
    if not x_internal_token or not verify_internal_token(x_internal_token):
        raise HTTPException(403, "Unauthorized — invalid internal token.")

    if not body.message.strip():
        raise HTTPException(400, "message is required.")

    context = "Test scenario run from Nova Command Center dashboard."
    if body.scenario:
        context += f" Scenario: {body.scenario}."

    # Run Nova
    response = await asyncio.to_thread(nova_respond, body.message, context)

    scenario_label = body.scenario or body.label or "free_text"

    # Log to AutomationLog
    log_automation(
        agent="nova",
        action_type="test_scenario",
        description=f"[TEST] {scenario_label} | Input: {body.message[:80]}",
        result=response[:200],
    )

    # Log to AgentMemory as CEO shadow training observation
    store_memory(
        agent="ceo_agent",
        memory_type="training_observation",
        content=(
            f"Scenario: {scenario_label}\n"
            f"Delta input: {body.message}\n"
            f"Nova response: {response}"
        ),
        subject=f"Training: {scenario_label}",
        importance=4,
        source="delta",
    )

    # Append to SOP_TRAINING_LOG.md so all agents can learn from it
    _append_training_log(scenario_label, body.message, response)

    return {
        "scenario": scenario_label,
        "message": body.message,
        "response": response,
        "logged": True,
        "sop_updated": True,
    }


# ── GET /nova/shadow-log ───────────────────────────────────────────────────────

@router.get("/shadow-log")
async def nova_shadow_log(
    limit: int = 20,
    x_internal_token: str = Header(None),
):
    """
    Return recent CEO shadow observations from AgentMemory.
    Requires INTERNAL_TOKEN header.
    """
    if not x_internal_token or not verify_internal_token(x_internal_token):
        raise HTTPException(403, "Unauthorized — invalid internal token.")

    from app.db import AsyncSessionLocal, AgentMemory
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AgentMemory)
            .where(AgentMemory.agent == "ceo_agent")
            .order_by(AgentMemory.created_at.desc())
            .limit(limit)
        )
        memories = result.scalars().all()

    return {
        "count": len(memories),
        "observations": [
            {
                "id": m.id,
                "memory_type": m.memory_type,
                "subject": m.subject,
                "content": m.content,
                "importance": m.importance,
                "source": m.source,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in memories
        ],
    }


# ── GET /nova/training-log ─────────────────────────────────────────────────────

@router.get("/training-log")
async def nova_training_log(x_internal_token: str = Header(None)):
    """
    Return the raw SOP_TRAINING_LOG.md content.
    Requires INTERNAL_TOKEN header.
    """
    if not x_internal_token or not verify_internal_token(x_internal_token):
        raise HTTPException(403, "Unauthorized — invalid internal token.")

    try:
        with open(TRAINING_LOG_PATH, "r") as f:
            content = f.read()
        return {"content": content, "path": "VERLYTAX_AIOS/SOPs/SOP_TRAINING_LOG.md"}
    except FileNotFoundError:
        return {"content": "No training scenarios logged yet.", "path": TRAINING_LOG_PATH}
