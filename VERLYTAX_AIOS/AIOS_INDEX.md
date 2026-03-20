# VERLYTAX AIOS — Master Index
## AI Operating System | Verlytax OS v4
### CEO: Delta | Last Updated: 2026-03-20

> This is the front door to the entire Verlytax AIOS.
> Every agent, every rule, every automation, and every decision tree lives in this folder.
> Read this file before navigating anything else in VERLYTAX_AIOS/.

---

## What Is VERLYTAX AIOS?

The **Verlytax AI Operating System** is the complete intelligence layer that runs a
1-person, AI-native freight dispatch company. No human dispatchers. No offshore staff.
Just Delta (CEO), the agents, and the carriers.

Every action — onboarding, dispatch, billing, compliance, escalation, SMS, retention —
is handled autonomously by the agent stack, governed by the Iron Rules, and logged in verlytax.db.

---

## Folder Map

```
VERLYTAX_AIOS/
├── AIOS_INDEX.md                    ← You are here (read first)
├── CONTEXT_OS.md                    ← 8-node context wheel — how the OS thinks
├── DECISION_ENGINE.md               ← 5-stage autonomous decision thresholds
├── AUTOMATION_SCHEDULE.md           ← Every automation: time / agent / trigger / action
├── BUILD_ROADMAP.md                 ← Phase 1→3 build plan with revenue targets
├── KENNETH_DISPATCH_MODULE.md       ← Kenneth's isolated carrier profile
└── agents/
    ├── DANIEL_EA.md                 ← Daniel: Executive Assistant system prompt
    ├── RECEPTIONIST.md              ← Inbound receptionist: qualifies leads
    ├── SDR_MEGAN.md                 ← Megan: outbound SDR carrier acquisition
    └── SDR_DAN.md                   ← Dan: outbound SDR carrier acquisition (B-voice)
```

---

## The Full Agent Stack

| Agent | Role | Status | System Prompt Location |
|---|---|---|---|
| **Erin** | AI Dispatcher — load booking, carrier comms, billing | **LIVE** | `Erin_System_Prompt_v4.txt` |
| **Nova** | Executive Assistant — Delta SMS alerts, Day 1 packets, fee alerts | **LIVE** | `app/services.py` (nova_*) |
| **Brain** | Master engine — FMCSA queries, DB, APScheduler crons | **LIVE** | `app/main.py` + `app/services.py` |
| **Daniel** | Executive Assistant — Delta's personal ops layer | **READY** | `VERLYTAX_AIOS/agents/DANIEL_EA.md` |
| **Receptionist** | Inbound qualifier — screens new carrier inquiries | **READY** | `VERLYTAX_AIOS/agents/RECEPTIONIST.md` |
| **Megan** | Outbound SDR — carrier acquisition cold outreach | **READY** | `VERLYTAX_AIOS/agents/SDR_MEGAN.md` |
| **Dan** | Outbound SDR — carrier acquisition (B-voice) | **READY** | `VERLYTAX_AIOS/agents/SDR_DAN.md` |
| **CEO Agent** | Shadow mode — learning Delta's decisions | **NOT BUILT** | Roadmap Phase 2 |

---

## The 11 Iron Rules (Never bypass in any file, any prompt, any code)

| # | Rule | Hard Block |
|---|---|---|
| 1 | No Florida loads — pickup OR delivery | YES |
| 2 | Min RPM $2.51 — absolute floor | YES |
| 3 | Max deadhead 50 miles OR 25% (whichever hits first) | YES |
| 4 | Max weight 48,000 lbs | YES |
| 5 | No Unsatisfactory or Conditional safety ratings | YES |
| 6 | Authority age 180+ days | YES |
| 7 | Failed FMCSA Clearinghouse → instant reject | YES |
| 8 | Blocked broker in memory_brokers → never rebook | YES |
| 9 | NDS enrollment confirmed before Day 1 load | YES |
| 10 | Authority age verified via live FMCSA portal | YES |
| 11 | Never release BOL before delivery confirmed | YES |

Full legal text: `IRON_RULES.md`
Code enforcement: `app/iron_rules.py`

---

## Quick Navigation

| I need to... | Go to... |
|---|---|
| Understand how the OS makes decisions | `CONTEXT_OS.md` |
| Know what an agent can handle alone vs. escalate | `DECISION_ENGINE.md` |
| See every automation and when it fires | `AUTOMATION_SCHEDULE.md` |
| Know the build plan and revenue roadmap | `BUILD_ROADMAP.md` |
| Add or review a specific carrier | `KENNETH_DISPATCH_MODULE.md` (template) |
| Deploy an SDR agent | `agents/SDR_MEGAN.md` or `agents/SDR_DAN.md` |
| Deploy the inbound receptionist | `agents/RECEPTIONIST.md` |
| Brief Delta's EA | `agents/DANIEL_EA.md` |
| Check what code is built | `CLAUDE.md` (root) |
| Check what can never change | `IRON_RULES.md` (root) |

---

## Current Business State (Phase 1)

- **Carriers active:** 0 (new business — first carriers in onboarding)
- **Revenue target:** $100K/year
- **Truck target:** 30–50 active trucks
- **USA only:** Phase 1 is US-only. Canada Phase 2 is on hold.
- **Database:** SQLite (dev) / PostgreSQL (Railway production)
- **Deployed on:** Railway — `Procfile` → `uvicorn app.main:app`

---

## Files Claude Code Cannot Touch

- `IRON_RULES.md` — Delta's law only
- `Erin_System_Prompt_v4.txt` — Delta's voice only
- `.env` — never read, never log, never touch
- `verlytax.db` — runtime DB, never commit, never manually edit

---

*Verlytax AIOS v1 | CEO: Delta | 2026-03-20*
