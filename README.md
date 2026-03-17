# Verlytax OS v4
### AI-Native Freight Dispatch | CEO: Delta | Built: Claude Code

> *"You drive. We handle the rest."*

---

## What Is Verlytax?

Verlytax is a 1-person, AI-native freight dispatch business. Every operation — from carrier onboarding to load booking to billing — runs through an AI agent stack built and governed by Delta.

This repository stores the system prompts, automation workflows, Iron Rules, and operational documentation that power Verlytax OS v4.

---

## Repository Structure

```
verlytax/
├── README.md                        # This file
├── IRON_RULES.md                    # 11 non-negotiable operating rules
├── agents/
│   └── Erin_System_Prompt_v4.txt    # Erin — AI Dispatcher (Production)
├── .github/
│   └── workflows/                   # GitHub Actions automations
```

---

## The Agent Stack

| Agent | Role | Status |
|---|---|---|
| **Erin** | AI Dispatcher — load booking, carrier comms, billing | ✅ Active |
| **Nova** | Executive Assistant — Delta SMS, escalations | ✅ Active |
| **Brain (CTO)** | Master decision engine, DB reads/writes | ✅ Active |
| **CEO Agent** | Shadow Mode — learning Delta's decisions | 🔒 Shadow Only |

---

## Iron Rules

11 rules. No exceptions. No bypasses. Ever.
See [`IRON_RULES.md`](./IRON_RULES.md) for the full list.

---

## Fee Structure

| Period | Fee |
|---|---|
| Trial (Days 1–7) | FREE |
| Months 1–4 (all carriers) | 8% of gross |
| Month 5+ (new carriers) | 10% of gross |
| Month 5+ (old carriers) | 8% for life |
| Extra services (any carrier) | +10% added to base |

Minimum weekly fee: **$100 USD**
Fee always calculated on **gross revenue first** — before factoring discount.

---

## Phase Status

| Phase | Region | Status |
|---|---|---|
| Phase 1 | USA | ✅ ACTIVE |
| Phase 2 | Canada | 🔒 Not Active |
| Phase 3 | EU / UK | 🔒 Not Active |

---

## Security

This repo is **public**. All system prompts, Iron Rules, and agent configurations are proprietary to Verlytax Operations.

- Never share API keys in this repo
- Never commit verlytax.db
- All carrier data stays in the database — never in flat files

---

*Verlytax OS v4 | CEO: Delta | Built with Claude Code*
