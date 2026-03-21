# TRAINING_INDEX.md — Verlytax Dispatcher Training

> This folder contains the knowledge base for training Verlytax agents and dispatchers.
> Content is sourced from real trucking industry coursework and adapted for Verlytax operations.
> All agents (Erin, Mya, etc.) can reference this material via load_agent_prompt() or /brain/sops.

---

## How This Connects to the Agent Stack

| Layer | Role |
|---|---|
| `VERLYTAX_AIOS/training/` | Raw training content (this folder) |
| `/brain/sops` API route | Serves any `.md` file here on demand |
| `load_agent_prompt()` in services.py | Injects training content into agent context |
| `mya_learn()` cron (daily 6 AM) | Mya absorbs training patterns into AgentMemory |
| `AgentMemory` table | Persistent recall — learned dispatch patterns stored per carrier/lane |

---

## Module Index

| Module | Title | Status |
|---|---|---|
| MODULE_01 | *(pending — upload course photos)* | Pending |
| MODULE_02 | *(pending — upload course photos)* | Pending |
| MODULE_03 | *(pending — upload course photos)* | Pending |

---

## Instructions for Delta

1. Upload photos of the trucking course book/manual in the Claude Code chat
2. Claude will read each photo, extract the content, and build the MODULE files
3. Each chapter or section becomes its own MODULE_XX file
4. Mya will absorb the modules automatically on the next daily 6 AM learn cycle

---

*Last updated: 2026-03-21 | Managed by: Claude Code*
