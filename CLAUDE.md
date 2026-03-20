# CLAUDE.md — Verlytax OS v4
## The Complete Context File for Claude Code

> This file is read automatically by Claude Code at the start of every session.
> It tells you exactly what this project is, what has been built, what the rules are,
> and how to behave when making changes. Read it fully before touching any code.

---

## What Is Verlytax?

A 1-person, AI-native freight dispatch business run by **Delta (CEO)**. Every operation runs through an AI agent stack. No human dispatchers. No offshore staff. Just Delta, the agents, and the carriers.

**Phase 1 Goal:** 30–50 active trucks generating ~$100K/year (USA only)

**Tagline:** *"You drive. We handle the rest."*

---

## Repository Layout — Current State

```
verlytax/
├── CLAUDE.md                          ← You are here (read first, always)
├── IRON_RULES.md                      ← 11 non-negotiable business rules
├── Erin_System_Prompt_v4.txt          ← Erin's full Claude system prompt
├── Procfile                           ← Railway: uvicorn app.main:app
├── requirements.txt                   ← Python deps (FastAPI, SQLAlchemy, etc.)
├── .env.example                       ← Template — copy to .env, never commit
├── README.md                          ← Public-facing project overview
├── app/
│   ├── main.py                        ← FastAPI entry + APScheduler crons
│   ├── db.py                          ← SQLAlchemy async models
│   ├── iron_rules.py                  ← Iron Rules enforcement logic
│   ├── services.py                    ← Nova SMS, Erin (Claude API), Stripe, FMCSA
│   └── routes/
│       ├── onboarding.py              ← Carrier onboarding (10-step flow)
│       ├── billing.py                 ← Load booking, BOL, fee collection
│       ├── escalation.py             ← Disputes, Delta escalations, broker blocks
│       └── webhooks.py               ← Stripe, Twilio SMS, Retell, internal crons
└── static/
    ├── dashboard.html                 ← Operations dashboard (served at /)
    ├── about.html                     ← About Verlytax (served at /about)
    ├── carrier-packet.html            ← Carrier onboarding packet (/carrier-packet)
    └── shipper-broker-packet.html     ← Broker info packet (/shipper-broker-packet)
```

---

## The Agent Stack

| Agent | Role | Status | Location |
|---|---|---|---|
| **Erin** | AI Dispatcher — load booking, carrier comms, billing | Active | `services.erin_respond()` + `Erin_System_Prompt_v4.txt` |
| **Nova** | Executive Assistant — Delta SMS alerts, Day 1 packets, fee alerts | Active | `services.nova_sms()`, `services.nova_alert_ceo()` |
| **Brain** | Master engine — FMCSA queries, DB, APScheduler crons | Active | `app/main.py` (scheduler) + `services.fmcsa_lookup()` |
| **CEO Agent** | Shadow mode — learning Delta's decisions | Shadow Only | Not yet built |

---

## Iron Rules — NEVER bypass these in code

See `IRON_RULES.md` for the full legal text. See `app/iron_rules.py` for enforcement logic.
`check_load_rules()` in `app/routes/billing.py` enforces all rules before any load books.

| # | Rule | Hard Block |
|---|---|---|
| 1 | No Florida loads — pickup OR delivery state | Yes |
| 2 | Min RPM $2.51 — hard floor, no exceptions | Yes |
| 3 | Max deadhead 50 miles OR 25% of trip (whichever is hit first) | Yes |
| 4 | Max weight 48,000 lbs | Yes |
| 5 | No carriers with Unsatisfactory or Conditional safety ratings | Yes |
| 6 | Authority age must be 180+ days | Yes |
| 7 | Failed FMCSA Clearinghouse check → instant reject | Yes |
| 8 | Blocked broker in `BlockedBroker` table → never rebook | Yes |
| 9 | NDS enrollment must be confirmed before Day 1 load | Yes |
| 10 | Authority age must be verified via live FMCSA portal (not self-reported) | Yes |
| 11 | Never release BOL before delivery is confirmed | Yes |

**Only Delta can modify an Iron Rule. Claude Code cannot weaken, skip, or work around any of these.**

---

## Database Models (`app/db.py`)

Four SQLAlchemy async models, all stored in `verlytax.db`:

| Model | Table | Purpose |
|---|---|---|
| `Carrier` | `carriers` | All carrier data: MC/DOT, status, billing, compliance |
| `Load` | `loads` | Every load booked: route, RPM, weight, BOL status |
| `BlockedBroker` | `blocked_brokers` | Permanently blocked brokers — never delete entries |
| `EscalationLog` | `escalation_logs` | All disputes and Delta escalations |

**Carrier status enum:** `lead → trial → active → suspended → churned`

**Load status enum:** `pending → in_transit → delivered → invoiced → paid`

**Never commit `verlytax.db` to git. Never store sensitive carrier data in flat files.**

---

## API Routes — What's Built

### Onboarding (`/onboarding/*`)
- `POST /onboarding/lead` — create new carrier lead
- `POST /onboarding/compliance-check` — run FMCSA + Iron Rules check
- `POST /onboarding/activate-trial` — start 7-day free trial + send Day 1 packet via Nova
- `POST /onboarding/convert` — convert trial to active (attaches Stripe customer)
- `GET /onboarding/carrier/{mc_number}` — get carrier record
- `POST /onboarding/fmcsa-lookup` — live FMCSA portal query

### Billing (`/billing/*`)
- `POST /billing/load/check` — dry-run Iron Rules check (no booking)
- `POST /billing/load/book` — book a load (runs all Iron Rules, saves to DB)
- `POST /billing/load/{load_id}/deliver` — confirm delivery, collect POD
- `POST /billing/load/bol-release` — release BOL (only after delivery confirmed)
- `POST /billing/collect-fee/{load_id}` — charge Stripe for dispatch fee
- `GET /billing/loads/{mc_number}` — list all loads for a carrier

### Escalation (`/escalation/*`)
- `POST /escalation/create` — log a new escalation or dispute
- `POST /escalation/dispute/action` — Erin resolves or escalates to Delta
- `POST /escalation/broker/block` — permanently block a broker
- `GET /escalation/blocked-brokers` — list all blocked brokers
- `GET /escalation/open` — list all open escalations

### Webhooks (`/webhooks/*`)
- `POST /webhooks/stripe` — Stripe payment events (signature-verified)
- `POST /webhooks/twilio/sms` — inbound carrier SMS → Erin responds
- `POST /webhooks/retell` — Retell voice call callbacks
- `POST /webhooks/internal` — internal cron triggers (token-protected)

### Core (`/`)
- `GET /` — dashboard (dashboard.html)
- `GET /about` — about page
- `GET /carrier-packet` — carrier onboarding packet
- `GET /shipper-broker-packet` — broker info packet
- `GET /health` — health check
- `GET /ping` — ping

---

## Scheduled Jobs (APScheduler in `app/main.py`)

Two crons run on startup via APScheduler:

| Job | Schedule | What it does |
|---|---|---|
| `check_trial_touchpoints()` | Daily at 9:00 AM UTC | Sends Day 3/7/14/30 win-back SMS via Nova to trial/churned carriers |
| `friday_fee_charge()` | Fridays at 10:00 AM UTC | Charges all active carriers' weekly fees via Stripe; suspends + alerts Delta on failure |

**Note:** The original design called for Monday auto-charge. This was changed to Friday in the actual implementation. Do not revert to Monday without Delta's approval.

---

## Services (`app/services.py`) — Key Functions

| Function | Purpose |
|---|---|
| `nova_sms(to, body)` | Send SMS via Twilio from Nova |
| `nova_alert_ceo(subject, body)` | Alert Delta directly (CEO phone only) |
| `nova_day1_carrier_packet(phone, name, mc)` | Send onboarding packet SMS on trial activation |
| `erin_respond(message, context)` | Call Claude API with Erin's system prompt, return response |
| `calculate_fee(gross_revenue, months_active, is_og)` | Returns fee amount in dollars (always on gross BEFORE factoring) |
| `charge_carrier_fee(stripe_customer_id, amount_cents, description)` | Charge carrier via Stripe |
| `fmcsa_lookup(mc_number)` | Live FMCSA portal query (async) |
| `verify_internal_token(token)` | Constant-time comparison for cron auth |
| `verify_twilio_signature(url, params, sig)` | Twilio webhook signature verification |

---

## Key Business Rules — Fee Structure

- Fee is ALWAYS calculated on **gross revenue BEFORE any factoring discount**
- Trial (Days 1–7): **FREE**
- Months 1–4 active: **8%**
- Month 5+ (new carriers): **10%**
- OG carriers (original/founding): **8% for life** — never increase
- Extra services add-on: **+10% on base fee**
- Weekly minimum: **$100/week**
- Auto-charge runs **Friday** via Stripe
- Charge failure → suspend carrier immediately + Nova alert to Delta

---

## Escalation Rules

| Situation | Who Handles |
|---|---|
| Any money decision over $500 | Delta only — escalate immediately |
| Carrier threatening to leave | Delta only |
| Billing dispute under $200 with clear evidence | Erin handles alone |
| Dispute unresolved after 48 hours | Auto-escalate to Delta |
| Any Iron Rule violation | Hard block — never negotiate |

---

## Communication Rules (Erin's Voice)

- Always open with: **"Hi, this is Erin with Verlytax Operations."**
- Never identify as: AI, bot, language model, Claude, ChatGPT, or any AI product
- Never give open-ended timing — always be specific: *"Hold it till 3 PM ET Friday."*
- Always end every interaction with a specific next step and a deadline
- Tone: professional, direct, confident — not robotic, not overly friendly

---

## What Still Needs to Be Built (Priority Order)

Items from the original roadmap that are **not yet implemented:**

1. **`/erin/chat` endpoint** — connect the dashboard chat box to `services.erin_respond()` so Delta can chat with Erin live from the dashboard
2. **Retell voice integration** — connect inbound carrier phone calls to Erin via Retell AI (webhook skeleton exists at `/webhooks/retell` but logic is not wired)
3. **Brain annual re-query** — FMCSA Clearinghouse re-check on all active carriers once per year (prevent carrying unsafe operators)
4. **Carrier retention flow** — send testimonial request SMS via Nova at Day 30 and Day 60
5. **DocuSign integration** — auto-send service agreement PDF at Day 5 of trial
6. **DAT rate feed** — pull live RPM data per lane for scoring in `services.py`
7. **Canada Phase 2** — NSC/CVOR/SAAQ compliance — **only build when Delta explicitly activates**

Items already completed (do not re-add to roadmap):
- ~~Monday auto-charge cron~~ → Built as Friday auto-charge in `main.py`
- ~~Win-back SMS sequence Day 3/7/14/30~~ → Built in `check_trial_touchpoints()`
- ~~Carrier onboarding flow~~ → Fully built in `routes/onboarding.py`
- ~~Load booking with Iron Rules~~ → Fully built in `routes/billing.py`
- ~~BOL release guard~~ → Enforced in `routes/billing.py`
- ~~Broker block system~~ → Built in `routes/escalation.py`

---

## Security Rules — Non-Negotiable

- Never put API keys or secrets in code — `.env` only, always
- Never commit `.env` or `verlytax.db` to git (both are in `.gitignore`)
- Always verify Stripe webhook signatures via `stripe.Webhook.construct_event()`
- Always verify Twilio webhook signatures via `verify_twilio_signature()`
- Use `hmac.compare_digest()` for all token comparisons — never `==`
- SQL injection guard: always use SQLAlchemy ORM — never raw string queries
- CEO phone whitelist: only `CEO_PHONE` from `.env` gets priority Nova routing
- Never expose `/docs` or `/redoc` in production — disable in `APP_ENV=production`

---

## Environment Variables (from `.env.example`)

| Variable | Purpose |
|---|---|
| `APP_ENV` | `production` or `development` |
| `SECRET_KEY` | 64-char random string for app security |
| `CEO_PHONE` | Delta's whitelisted phone (E.164 format) |
| `DATABASE_URL` | SQLite for dev, Postgres for Railway prod |
| `ANTHROPIC_API_KEY` | Claude API key for Erin |
| `TWILIO_ACCOUNT_SID` | Twilio for Nova SMS |
| `TWILIO_AUTH_TOKEN` | Twilio webhook verification |
| `TWILIO_FROM_NUMBER` | Nova's outbound SMS number |
| `RETELL_API_KEY` | Retell AI for voice calls |
| `STRIPE_SECRET_KEY` | Stripe for fee collection |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signature verification |
| `FMCSA_API_KEY` | Live FMCSA portal queries |
| `INTERNAL_TOKEN` | Auth token for `/webhooks/internal` cron triggers |

---

## How to Deploy on Railway

1. Connect this repo to Railway
2. Set all env vars from `.env.example` in Railway dashboard (never in code)
3. Railway detects `Procfile` → runs: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. On startup, `init_db()` creates `verlytax.db` and APScheduler starts both crons
5. Dashboard live at your Railway URL at `/`

---

## Dev Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and fill in env file
cp .env.example .env

# Run locally with hot reload
uvicorn app.main:app --reload --port 8000

# View auto-generated API docs (dev only — disabled in production)
open http://localhost:8000/docs
```

---

## Files Claude Code Must Never Modify

- `IRON_RULES.md` — Iron Rules are Delta's law, not code to be refactored
- `Erin_System_Prompt_v4.txt` — Erin's voice and persona, only Delta changes this
- `.env` — never touch, never read, never log
- `verlytax.db` — runtime database, never committed, never manually edited via code

---

*Verlytax OS v4 | CEO: Delta | Built with Claude Code | Last updated: 2026-03-20*
