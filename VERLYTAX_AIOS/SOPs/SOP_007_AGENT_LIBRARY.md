# SOP_007 — Agent Library Management
**Version:** 1.0 | **Owner:** Delta | **Enforced by:** Brain

---

## Purpose

The Agent Library is how Delta adds new AI agents to the Verlytax system —
storing their system prompts, testing them, and activating them without a code deploy.
Agents are stored as `.md` files in `VERLYTAX_AIOS/agents/` and can be run on demand
via the `/brain/agents/{filename}/run` endpoint.

---

## How to Upload a New Agent

1. Prepare the agent's system prompt as a markdown file
2. Call `POST /brain/agents` with:
   - `filename`: e.g. `FREIGHT_SPECIALIST.md`
   - `content`: the full system prompt text
   - `x-internal-token`: your INTERNAL_TOKEN
3. The agent is immediately stored and available for testing

---

## How to Test an Agent

Before activating an agent for live use:

1. Call `POST /brain/agents/{filename}/run` with:
   - `message`: a test message the agent should respond to
   - `context`: optional JSON context (carrier data, load data, etc.)
   - `x-internal-token`: your INTERNAL_TOKEN
2. Review the reply — does it respond correctly? Does it follow Verlytax tone?
3. Iterate on the prompt content by re-uploading with `POST /brain/agents`

---

## How to Activate an Agent for Live Use

Once tested and approved by Delta:

1. Add the agent to the routes in `app/routes/agents.py` or create a new route
2. Wire it through `run_agent(filename, message, context)` in services.py
3. Document it in the Agent Stack section of CLAUDE.md

---

## Protected Core Agents (Cannot Be Deleted)

These agents power critical Verlytax operations and are permanently protected:

| Agent | Role |
|---|---|
| `MYA.md` | Intelligence + memory engine |
| `CORA.md` | Compliance officer |
| `ZARA.md` | Customer support |
| `RECEPTIONIST.md` | Inbound lead qualifier |
| `SDR_MEGAN.md` | Outbound SDR (cold outreach) |
| `SDR_DAN.md` | Outbound SDR (B-voice) |
| `DANIEL_EA.md` | Delta's Executive Assistant |

Attempting to delete any protected agent via the API returns HTTP 403.

---

## What Makes a Good Agent Prompt

- Clear role definition in the first line: "You are [Name], [role] for Verlytax Operations."
- Specific instructions for tone, format, and decision rules
- Explicit list of what the agent CAN and CANNOT do
- Any Iron Rules the agent must enforce (reference IRON_RULES.md)
- Output format instructions (JSON, plain text, SMS, etc.)

---

## API Reference

| Endpoint | Token Required | Action |
|---|---|---|
| `GET /brain/agents` | No | List all agent files |
| `GET /brain/agents/{filename}` | No | Read agent content |
| `POST /brain/agents` | Yes | Upload/save new agent |
| `DELETE /brain/agents/{filename}` | Yes | Delete a custom agent |
| `POST /brain/agents/{filename}/run` | Yes | Test-run any agent |

---

*SOP_007 v1.0 | Verlytax OS v4 | Created 2026-03-21*
