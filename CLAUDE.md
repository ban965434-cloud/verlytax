# CLAUDE.md — Verlytax OS v4
## How to build Delta's AI Dispatcher Business

> This file tells Claude Code exactly how Verlytax works, what the rules are, and how to build it out correctly.

---

## What Is Verlytax?

A 1-person, AI-native freight dispatch business run by **Delta (CEO)**. Every operation runs through an AI agent stack. The goal is 30–50 active trucks generating ~$100K/year for Phase 1 USA.

**"You drive. We handle the rest."**

---

## Repository Layout

```
verlytax/
├── CLAUDE.md                          ← You are here
├── IRON_RULES.md                      ← 11 non-negotiable rules
├── Erin_System_Prompt_v4.txt          ← Erin's full system prompt
├── Procfile                           ← Railway deployment
├── requirements.txt                   ← Python dependencies
├── .env.example                       ← Copy to .env, never commit
├── app/
│   ├── main.py                        ← FastAPI entry point
│   ├── db.py                          ← SQLAlchemy models (verlytax.db)
│   ├── iron_rules.py                  ← Iron Rules enforcer (pure logic)
│   ├── services.py                    ← Nova SMS, Erin (Claude), Stripe, FMCSA
│   └── routes/
│       ├── onboarding.py              ← 10-step carrier onboarding
│       ├── billing.py                 ← Load booking + fee collection
│       ├── escalation.py             ← Disputes + Delta escalations
│       └── webhooks.py               ← Stripe, Twilio, Retell callbacks
└── static/
    └── dashboard.html                 ← Operations dashboard (served at /)
```

---

## The Agent Stack

| Agent | Role | Status |
|---|---|---|
| **Erin** | AI Dispatcher — load booking, carrier comms, billing | Active |
| **Nova** | Executive Assistant — Delta SMS, Day 1 packets, fee alerts | Active |
| **Brain** | Master engine — FMCSA queries, DB, scheduler | Active |
| **CEO Agent** | Shadow mode — learning Delta's decisions | Shadow Only |

---

## Iron Rules — NEVER bypass these

See `IRON_RULES.md` and `app/iron_rules.py` for enforcement code.

| # | Rule |
|---|---|
| 1 | No Florida loads (pickup OR delivery) |
| 2 | Min RPM $2.51 — hard floor |
| 3 | Max deadhead 50 miles / 25% |
| 4 | Max weight 48,000 lbs |
| 5 | No Unsatisfactory/Conditional safety ratings |
| 6 | Authority age 180+ days |
| 7 | Failed FMCSA Clearinghouse → instant reject |
| 8 | Blocked broker in memory_brokers → never rebook |
| 9 | NDS enrollment before Day 1 load |
| 10 | Authority age verified via live FMCSA portal |
| 11 | Never release BOL before delivery confirmed |

**Only Delta can modify an Iron Rule.**

---

## Key Business Rules for Claude Code

### Fees
- Fee is ALWAYS on **gross revenue BEFORE factoring discount**
- Trial (Days 1–7): FREE
- Months 1–4: 8% | Month 5+ new: 10% | OG carriers: 8% for life
- Extra services: +10% on base | Minimum: $100/week
- Auto-charge Monday via Stripe — failed = suspend carrier + Nova alert to Delta

### Escalation
- Any money decision over $500 → **escalate to Delta immediately**
- Carrier threatening to leave → Delta only
- Billing disputes under $200 with clear evidence → Erin handles alone
- Dispute unresolved 48 hours → auto-escalate to Delta

### Databases
- `verlytax.db` — master: carriers, loads, compliance, billing, escalations
- `memory_brokers` (BlockedBroker table) — permanently blocked brokers
- `memory_loads` (Load table) — active load tracking
- **Never store sensitive carrier data in flat files**
- **Never commit verlytax.db to git**

### Communication (Erin's voice)
- Always: "Hi, this is Erin with Verlytax Operations."
- Never say: AI, bot, language model, Claude, ChatGPT
- Never open-ended timing — always specific: "Hold it till 3 PM."
- End every interaction with a specific next step + deadline

---

## How to Deploy on Railway

1. Connect repo to Railway
2. Set all env vars from `.env.example` in Railway dashboard
3. Railway detects `Procfile` → runs: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. App starts → `init_db()` creates `verlytax.db` automatically
5. Dashboard live at your Railway URL `/`

---

## What to Build Next (Priority Order)

1. **`/erin/chat` endpoint** — connect dashboard chat box to Claude API via `services.erin_respond()`
2. **Retell voice integration** — connect inbound carrier calls to Erin
3. **Monday auto-charge cron** — `/webhooks/internal` with `monday_fee_charge` action
4. **Brain annual re-query scheduler** — FMCSA Clearinghouse on all active carriers yearly
5. **Win-back sequence** — Day 3/7/14/30 post-trial SMS via Nova
6. **Carrier retention flow** — testimonial triggers at Day 30/60
7. **DocuSign integration** — auto-send service agreement at Day 5 of trial
8. **DAT rate feed** — pull live RPM data for lane scoring in `services.py`
9. **Canada Phase 2** — only when Delta activates (NSC/CVOR/SAAQ compliance)

---

## Security Rules for Claude Code

- Never put API keys in code — use `.env` only
- Never commit `.env` or `verlytax.db`
- Always verify Stripe/Twilio/Retell webhook signatures before processing
- Use `hmac.compare_digest()` for all token comparisons
- SQL injection guard: always use SQLAlchemy ORM, never raw string queries
- CEO phone whitelist: only Delta's number gets priority routing

---

## Dev Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Copy env file
cp .env.example .env
# (fill in your real keys)

# Run locally
uvicorn app.main:app --reload --port 8000

# View API docs (dev only)
open http://localhost:8000/docs
```

---

*Verlytax OS v4 | CEO: Delta | Built with Claude Code*
