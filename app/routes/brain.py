"""
Verlytax OS v4 — Brain Control Routes
SOP management, automation audit log, and governance rule toggles.
Delta controls all autonomous behaviors from here.
"""

import asyncio
import os
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db import get_db, AutomationLog, AutomationRule
from app.services import verify_internal_token, run_agent, log_automation

router = APIRouter()

# SOP folder path (repo)
SOP_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "VERLYTAX_AIOS", "SOPs")
)

# Agent folder path (repo)
AGENT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "VERLYTAX_AIOS", "agents")
)

# Core agents — never allow deletion (code-level dependencies)
PROTECTED_AGENTS = frozenset({
    "MYA.md", "CORA.md", "ZARA.md", "RECEPTIONIST.md",
    "SDR_MEGAN.md", "SDR_DAN.md", "DANIEL_EA.md"
})


# ── Schemas ───────────────────────────────────────────────────────────────────

class SopCreate(BaseModel):
    filename: str   # e.g. "SOP_004_RETELL_CALLS.md"
    content: str

class AgentCreate(BaseModel):
    filename: str   # e.g. "CUSTOM_AGENT.md"
    content: str    # full system prompt / agent markdown

class AgentRunRequest(BaseModel):
    message: str
    context: Optional[str] = None


# ── SOP Management ────────────────────────────────────────────────────────────

@router.get("/sops")
async def list_sops():
    """List all SOP files in VERLYTAX_AIOS/SOPs/."""
    if not os.path.isdir(SOP_DIR):
        return {"sops": [], "note": "SOPs folder not found"}
    files = sorted(f for f in os.listdir(SOP_DIR) if f.endswith(".md"))
    return {"sops": files, "count": len(files), "path": "VERLYTAX_AIOS/SOPs/"}


@router.get("/sops/{filename}")
async def get_sop(filename: str):
    """Read a specific SOP by filename."""
    if not filename.endswith(".md"):
        filename += ".md"
    path = os.path.join(SOP_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(404, f"SOP '{filename}' not found.")
    with open(path, "r") as f:
        content = f.read()
    return {"filename": filename, "content": content}


@router.post("/sops")
async def create_sop(
    data: SopCreate,
    x_internal_token: str = Header(...),
):
    """
    Create or overwrite a SOP markdown file in VERLYTAX_AIOS/SOPs/.
    Requires INTERNAL_TOKEN header.
    """
    if not verify_internal_token(x_internal_token):
        raise HTTPException(403, "Invalid internal token.")

    filename = data.filename if data.filename.endswith(".md") else f"{data.filename}.md"

    # Safety: no path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "Invalid filename.")

    path = os.path.join(SOP_DIR, filename)
    os.makedirs(SOP_DIR, exist_ok=True)
    with open(path, "w") as f:
        f.write(data.content)

    return {"status": "saved", "filename": filename, "path": f"VERLYTAX_AIOS/SOPs/{filename}"}


# ── Automation Log ─────────────────────────────────────────────────────────────

@router.get("/automation-log")
async def get_automation_log(
    limit: int = 50,
    offset: int = 0,
    agent: Optional[str] = None,
    carrier_mc: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Paginated audit log of every autonomous action Brain, Erin, or any agent has taken."""
    query = select(AutomationLog).order_by(AutomationLog.created_at.desc())
    if agent:
        query = query.where(AutomationLog.agent == agent)
    if carrier_mc:
        query = query.where(AutomationLog.carrier_mc == carrier_mc)
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    logs = result.scalars().all()

    return {
        "total": len(logs),
        "offset": offset,
        "logs": [
            {
                "id": l.id,
                "agent": l.agent,
                "action_type": l.action_type,
                "carrier_mc": l.carrier_mc,
                "load_id": l.load_id,
                "description": l.description,
                "result": l.result,
                "escalated_to_delta": l.escalated_to_delta,
                "created_at": l.created_at,
            }
            for l in logs
        ],
    }


# ── Automation Rule Governance ─────────────────────────────────────────────────

@router.get("/rules")
async def list_rules(db: AsyncSession = Depends(get_db)):
    """List all automation rules and their current enabled/disabled state."""
    result = await db.execute(select(AutomationRule).order_by(AutomationRule.id))
    rules = result.scalars().all()
    return {
        "rules": [
            {
                "id": r.id,
                "rule_key": r.rule_key,
                "description": r.description,
                "enabled": r.enabled,
                "updated_at": r.updated_at,
            }
            for r in rules
        ]
    }


@router.post("/rules/{rule_key}/toggle")
async def toggle_rule(
    rule_key: str,
    x_internal_token: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Enable or disable an automation rule instantly — no code deploy needed.
    Requires INTERNAL_TOKEN header.
    """
    if not verify_internal_token(x_internal_token):
        raise HTTPException(403, "Invalid internal token.")

    result = await db.execute(
        select(AutomationRule).where(AutomationRule.rule_key == rule_key)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(404, f"Rule '{rule_key}' not found.")

    rule.enabled = not rule.enabled
    rule.updated_at = datetime.utcnow()
    await db.commit()

    return {
        "rule_key": rule_key,
        "enabled": rule.enabled,
        "message": f"Rule '{rule_key}' {'ENABLED' if rule.enabled else 'DISABLED'}.",
    }


# ── Agent Library — Upload, Store, and Run Custom Agents ──────────────────────

@router.get("/agents")
async def list_agents():
    """List all agent files in VERLYTAX_AIOS/agents/."""
    if not os.path.isdir(AGENT_DIR):
        return {"agents": [], "note": "Agents folder not found"}
    files = sorted(f for f in os.listdir(AGENT_DIR) if f.endswith(".md"))
    return {
        "agents": files,
        "count": len(files),
        "path": "VERLYTAX_AIOS/agents/",
        "protected": list(PROTECTED_AGENTS),
    }


@router.get("/agents/{filename}")
async def get_agent(filename: str):
    """Read a specific agent file by filename."""
    if not filename.endswith(".md"):
        filename += ".md"
    path = os.path.join(AGENT_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(404, f"Agent '{filename}' not found.")
    with open(path, "r") as f:
        content = f.read()
    return {
        "filename": filename,
        "content": content,
        "is_protected": filename in PROTECTED_AGENTS,
    }


@router.post("/agents")
async def upload_agent(
    data: AgentCreate,
    x_internal_token: str = Header(...),
):
    """
    Upload and save a new agent prompt to VERLYTAX_AIOS/agents/.
    Use this to add agents Delta has found from external sources.
    Requires INTERNAL_TOKEN header.
    """
    if not verify_internal_token(x_internal_token):
        raise HTTPException(403, "Invalid internal token.")

    filename = data.filename if data.filename.endswith(".md") else f"{data.filename}.md"

    # Safety: no path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "Invalid filename.")

    path = os.path.join(AGENT_DIR, filename)
    os.makedirs(AGENT_DIR, exist_ok=True)
    with open(path, "w") as f:
        f.write(data.content)

    return {
        "status": "saved",
        "filename": filename,
        "path": f"VERLYTAX_AIOS/agents/{filename}",
        "is_protected": filename in PROTECTED_AGENTS,
    }


@router.delete("/agents/{filename}")
async def delete_agent(
    filename: str,
    x_internal_token: str = Header(...),
):
    """
    Delete a custom agent file from VERLYTAX_AIOS/agents/.
    Core system agents are permanently protected and cannot be deleted.
    Requires INTERNAL_TOKEN header.
    """
    if not verify_internal_token(x_internal_token):
        raise HTTPException(403, "Invalid internal token.")

    if not filename.endswith(".md"):
        filename += ".md"

    if filename in PROTECTED_AGENTS:
        raise HTTPException(403, f"'{filename}' is a core system agent and cannot be deleted.")

    path = os.path.join(AGENT_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(404, f"Agent '{filename}' not found.")

    os.remove(path)
    return {"status": "deleted", "filename": filename}


@router.post("/agents/{filename}/run")
async def run_agent_endpoint(
    filename: str,
    data: AgentRunRequest,
    x_internal_token: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Test-run any stored agent with a message.
    Agent file must exist in VERLYTAX_AIOS/agents/.
    Requires INTERNAL_TOKEN header.
    """
    if not verify_internal_token(x_internal_token):
        raise HTTPException(403, "Invalid internal token.")

    if not filename.endswith(".md"):
        filename += ".md"

    path = os.path.join(AGENT_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(404, f"Agent '{filename}' not found.")

    reply = await asyncio.to_thread(run_agent, filename, data.message, data.context or "")

    log_automation(
        agent=filename,
        action_type="agent_test_run",
        description=f"Test run: {data.message[:100]}",
        result="completed",
    )

    return {
        "agent": filename,
        "message": data.message,
        "reply": reply,
    }
