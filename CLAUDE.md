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
│   ├── main.py                        ← FastAPI entry + APScheduler crons (9 jobs)
│   ├── db.py                          ← SQLAlchemy async models
│   ├── iron_rules.py                  ← Iron Rules enforcement logic
│   ├── gdrive.py                      ← Google Drive folder creation
│   ├── services.py                    ← Nova SMS, Erin (Claude API), Stripe, FMCSA, agent helpers
│   └── routes/
│       ├── onboarding.py              ← Carrier onboarding (10-step flow)
│       ├── billing.py                 ← Load booking, BOL, fee collection
│       ├── escalation.py             ← Disputes, Delta escalations, broker blocks
│       ├── webhooks.py               ← Stripe, Twilio SMS, Retell, internal crons
│       ├── carriers.py               ← Carrier list, bulk import, CSV export
│       ├── brain.py                  ← SOP CRUD, automation log, rule toggles (/brain/*)
│       ├── agents.py                 ← Receptionist, Megan SDR (/agents/*)
│       ├── workflows.py              ← Multi-agent workflow pipelines (/workflows/*)
│       ├── mya.py                    ← Mya memory engine (/mya/*)
│       ├── compliance.py             ← Cora compliance monitoring (/compliance/*)
│       └── support.py                ← Zara customer support tickets (/support/*)
├── static/
│   ├── dashboard.html                 ← Operations dashboard (served at /)
│   ├── about.html                     ← About Verlytax (served at /about)
│   ├── carrier-packet.html            ← Carrier onboarding packet (/carrier-packet)
│   └── shipper-broker-packet.html     ← Broker info packet (/shipper-broker-packet)
└── VERLYTAX_AIOS/
    ├── AIOS_INDEX.md                  ← AIOS front door (read first)
    ├── CONTEXT_OS.md                  ← 8-node context wheel
    ├── DECISION_ENGINE.md             ← 5-stage decision thresholds
    ├── AUTOMATION_SCHEDULE.md         ← Every cron and event trigger
    ├── BUILD_ROADMAP.md               ← Phase 1→3 build + revenue targets
    ├── KENNETH_DISPATCH_MODULE.md     ← Carrier profile template
    ├── SOPs/                          ← Standard Operating Procedures (text, versioned)
    │   ├── SOP_INDEX.md               ← SOP master index
    │   ├── SOP_001_CARRIER_ONBOARDING.md
    │   ├── SOP_002_LOAD_BOOKING.md
    │   └── SOP_003_DISPUTE_RESOLUTION.md
    │   ├── SOP_004_COMPLIANCE_MONITORING.md
    │   └── SOP_005_CUSTOMER_SUPPORT.md
    └── agents/
        ├── DANIEL_EA.md               ← Delta's EA system prompt
        ├── RECEPTIONIST.md            ← Inbound qualifier (Ava)
        ├── SDR_MEGAN.md               ← Outbound SDR (cold outreach)
        ├── SDR_DAN.md                 ← Outbound SDR (B-voice)
        ├── MYA.md                     ← Intelligence & memory engine
        ├── CORA.md                    ← Compliance officer
        └── ZARA.md                    ← Customer support specialist
```

---

## The Agent Stack

| Agent | Role | Status | Location |
|---|---|---|---|
| **Erin** | AI Dispatcher — load booking, carrier comms, billing, proactive SMS | Active | `services.erin_respond()` + `Erin_System_Prompt_v4.txt` |
| **Nova** | Executive Assistant — Delta SMS alerts, Day 1 packets, fee alerts | Active | `services.nova_sms()`, `services.nova_alert_ceo()` |
| **Mya** | Intelligence & memory engine — learns from every operation, powers all automations | Active | `app/main.py` (9 scheduler jobs) + `VERLYTAX_AIOS/agents/MYA.md` |
| **Ava** | Inbound qualifier — screens new carrier inquiries | Active | `app/routes/agents.py` + `VERLYTAX_AIOS/agents/RECEPTIONIST.md` |
| **Megan SDR** | Outbound SDR — carrier acquisition, professional woman voice, single consolidated SDR | Active | `app/routes/agents.py` + `VERLYTAX_AIOS/agents/SDR_MEGAN.md` |
| **Cora** | Compliance Officer — monitors authority, COI, insurance, clearinghouse, NDS weekly | Active | `app/routes/compliance.py` + `VERLYTAX_AIOS/agents/CORA.md` |
| **Zara** | Customer Support Specialist — tickets, billing questions, load issues, account inquiries | Active | `app/routes/support.py` + `VERLYTAX_AIOS/agents/ZARA.md` |
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

Six SQLAlchemy async models, all stored in `verlytax.db`:

| Model | Table | Purpose |
|---|---|---|
| `Carrier` | `carriers` | All carrier data: MC/DOT, status, billing, compliance |
| `Load` | `loads` | Every load booked: route, RPM, weight, BOL status |
| `BlockedBroker` | `blocked_brokers` | Permanently blocked brokers — never delete entries |
| `EscalationLog` | `escalation_logs` | All disputes and Delta escalations |
| `AutomationLog` | `automation_logs` | Audit trail for every autonomous action — never deleted |
| `AutomationRule` | `automation_rules` | Governance toggles — Delta enables/disables automations |
| `AgentMemory` | `agent_memories` | Mya's memory store — carrier profiles, lane insights, business learning |
| `ComplianceAudit` | `compliance_audits` | Full audit record per carrier per scan — authority, COI, insurance, NDS |
| `SupportTicket` | `support_tickets` | Zara ticket records — TKT-XXXX numbering, triage, response, resolution |

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

### Carriers (`/carriers/*`)
- `POST /carriers/import` — bulk CSV import of carrier leads
- `GET /carriers/list` — paginated carrier list with search + status filter
- `GET /carriers/stats` — pipeline snapshot (counts by status)
- `GET /carriers/export/csv` — export carrier list as CSV
- `POST /carriers/generate-leads` — manually trigger FMCSA + DAT lead gen (requires INTERNAL_TOKEN); accepts optional `states` list to override defaults

### Brain (`/brain/*`)
- `GET /brain/sops` — list all SOPs in VERLYTAX_AIOS/SOPs/
- `GET /brain/sops/{filename}` — read a specific SOP
- `POST /brain/sops` — create/overwrite a SOP (requires INTERNAL_TOKEN)
- `GET /brain/automation-log` — paginated audit log of all autonomous actions
- `GET /brain/rules` — list all automation rules + enabled state
- `POST /brain/rules/{rule_key}/toggle` — enable/disable any automation rule (requires INTERNAL_TOKEN)
- `POST /brain/setup-drive` — one-time Google Drive folder structure setup

### Agents (`/agents/*`)
- `POST /agents/receptionist` — run inbound lead through Receptionist agent (requires INTERNAL_TOKEN)
- `POST /agents/sdr/megan` — Megan SDR drafts outbound carrier acquisition SMS (requires INTERNAL_TOKEN)
- `POST /agents/voice-call` — initiate a Retell outbound call for any voice agent: Erin, Ava, or Zara (requires INTERNAL_TOKEN)

### Erin Chat (`/erin/*`)
- `POST /erin/chat` — live chat with Erin from the dashboard

### Compliance (`/compliance/*`)
- `GET /compliance/dashboard` — snapshot: at-risk count, expiring COIs, recent audits
- `POST /compliance/audit/{mc_number}` — run full Cora audit on one carrier (requires INTERNAL_TOKEN)
- `GET /compliance/audits` — list compliance audits (filter by mc_number, overall_passed, limit)
- `GET /compliance/at-risk` — all carriers with open compliance flags
- `GET /compliance/expiring-cois` — carriers with COI expiring within 60 days

### Support (`/support/*`)
- `POST /support/ticket` — create support ticket; Zara auto-triages immediately
- `GET /support/tickets` — list tickets (filter: status, priority, carrier_mc, assigned_to; paginated)
- `GET /support/tickets/{ticket_id}` — full ticket detail
- `POST /support/tickets/{ticket_id}/respond` — Zara drafts + sends SMS response (requires INTERNAL_TOKEN)
- `POST /support/tickets/{ticket_id}/resolve` — mark resolved (requires INTERNAL_TOKEN)
- `POST /support/tickets/{ticket_id}/escalate` — escalate to "erin", "delta", or "voice_agent" (requires INTERNAL_TOKEN)
- `POST /support/tickets/{ticket_id}/voice-escalate` — place Retell outbound call to carrier; transcript written back to ticket on call end (requires INTERNAL_TOKEN)
- `POST /support/chat` — live chat with Zara (no token required)
- `GET /support/stats` — open count, avg resolution time, by category/status

### Core (`/`)
- `GET /` — dashboard (dashboard.html)
- `GET /about` — about page
- `GET /carrier-packet` — carrier onboarding packet
- `GET /shipper-broker-packet` — broker info packet
- `GET /health` — health check
- `GET /ping` — ping

---

## Scheduled Jobs (APScheduler in `app/main.py`)

Nine crons run on startup via APScheduler. All governed by `AutomationRule` toggles — Delta can disable any via `POST /brain/rules/{rule_key}/toggle`.

| Job | Schedule | Rule Key | What it does |
|---|---|---|---|
| `check_trial_touchpoints()` | Daily 9:00 AM UTC | *(always on)* | Day 3/7/14/30 SMS to trial/churned carriers |
| `friday_fee_charge()` | Fridays 10:00 AM UTC | *(always on)* | Charges active carriers weekly; suspends on failure |
| `coi_expiry_check()` | Daily 7:00 AM UTC | `coi_expiry_check` | Alerts Delta + SMS carrier when COI within 30 days |
| `testimonial_sms()` | Daily 10:30 AM UTC | `testimonial_sms` | Day 30 feedback SMS + Day 60 review ask to active carriers |
| `annual_fmcsa_recheck()` | Jan 1, 6:00 AM UTC | `annual_fmcsa_recheck` | Re-checks FMCSA for all active carriers; suspends failures |
| `brain_autonomous_scan()` | Daily 8:00 AM UTC | `overdue_load_scan` / `no_load_carrier_scan` / `stale_lead_scan` | Scans for overdue loads, inactive active carriers, stale leads |
| `mya_learn()` | Daily 6:00 AM UTC | `mya_learn` | Synthesizes load/dispute data into AgentMemory for learning |
| `cora_compliance_scan()` | Mondays 7:30 AM UTC | `cora_compliance_scan` | Full compliance audit of all active + trial carriers; suspends RED violations |
| `support_ticket_sweep()` | Daily 9:30 AM UTC | `support_ticket_sweep` | Zara follow-up SMS on tickets >24h; auto-escalates tickets >48h to Delta |
| `megan_sdr_outreach()` | Daily 11:00 AM UTC | `megan_sdr_outreach` | Megan auto-contacts stale leads (14+ days, no conversion); up to 20 per run via Nova SMS |
| `fmcsa_lead_gen()` | Daily 6:30 AM UTC | `fmcsa_lead_gen` | FMCSA + DAT search across TX/Midwest/SE target states; auto-seeds qualifying dry van carriers as LEAD; max 200/day; Delta gets Nova summary |

**Note:** Friday fee charge was changed from Monday in the original design. Do not revert without Delta's approval.

---

## Services (`app/services.py`) — Key Functions

| Function | Purpose |
|---|---|
| `nova_sms(to, body)` | Send SMS via Twilio from Nova |
| `nova_alert_ceo(subject, body)` | Alert Delta directly (CEO phone only) |
| `nova_day1_carrier_packet(phone, name, mc)` | Send onboarding packet SMS on trial activation |
| `erin_respond(message, context)` | Call Claude API with Erin's system prompt, return response |
| `calculate_fee(gross_revenue, carrier_active_since, trial_start, has_extra_services, is_og)` | Returns fee amount in dollars (always on gross BEFORE factoring) |
| `charge_carrier_fee(stripe_customer_id, amount_cents, description)` | Charge carrier via Stripe |
| `fmcsa_lookup(mc_number)` | Live FMCSA portal query (async) |
| `log_automation(agent, action_type, description, result, ...)` | Write to automation_logs — call from any cron or trigger |
| `load_agent_prompt(filename)` | Load agent system prompt from VERLYTAX_AIOS/agents/{filename} |
| `run_agent(system_prompt_file, message, context)` | Run any agent (Megan, Dan, Receptionist) through Claude |
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

1. **Retell inbound phone number routing** — wire a Retell phone number to receive inbound calls and route to Erin or Ava based on caller context (outbound calls + webhook + per-agent IDs are all built; remaining step is Retell dashboard config to point a phone number at the right agent)
2. **DocuSign integration** — auto-send service agreement PDF at Day 5 of trial
3. **DAT rate feed** — pull live RPM data per lane for scoring in `services.py`
4. **Canada Phase 2** — NSC/CVOR/SAAQ compliance — **only build when Delta explicitly activates**

Items already completed (do not re-add to roadmap):
- ~~Monday auto-charge cron~~ → Built as Friday auto-charge in `main.py`
- ~~Win-back SMS sequence Day 3/7/14/30~~ → Built in `check_trial_touchpoints()`
- ~~Carrier onboarding flow~~ → Fully built in `routes/onboarding.py`
- ~~Load booking with Iron Rules~~ → Fully built in `routes/billing.py`
- ~~BOL release guard~~ → Enforced in `routes/billing.py`
- ~~Broker block system~~ → Built in `routes/escalation.py`
- ~~`/erin/chat` endpoint~~ → Live in `app/main.py`
- ~~Brain annual FMCSA re-check~~ → Built as `annual_fmcsa_recheck()` cron in `main.py`
- ~~Carrier retention Day 30/60 SMS~~ → Built as `testimonial_sms()` cron in `main.py`
- ~~Autonomous Brain scan~~ → Built as `brain_autonomous_scan()` cron in `main.py`
- ~~Wire existing agents (Receptionist, Megan, Dan)~~ → Live in `app/routes/agents.py`
- ~~SOP + knowledge storage~~ → `VERLYTAX_AIOS/SOPs/` + Google Drive folders added
- ~~Automation governance layer~~ → `AutomationLog`, `AutomationRule` models + `/brain/rules` endpoints
- ~~Retell voice integration (code)~~ → `retell_initiate_call()` service, `/agents/voice-call`, `/webhooks/retell` fully routed by agent (Erin/Ava/Zara), per-agent IDs in `.env`, transcript written back to ticket

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
| `RETELL_API_KEY` | Retell AI API key |
| `RETELL_AGENT_ID_ERIN` | Retell agent ID for inbound carrier dispatch calls (Erin) |
| `RETELL_AGENT_ID_AVA` | Retell agent ID for inbound new lead qualification calls (Ava) |
| `RETELL_AGENT_ID_ZARA` | Retell agent ID for outbound support escalation calls (Zara) |
| `STRIPE_SECRET_KEY` | Stripe for fee collection |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signature verification |
| `FMCSA_API_KEY` | Live FMCSA portal queries + daily lead gen state search |
| `DAT_API_KEY` | DAT One API for load board carrier search (leave blank until credentials obtained — lead gen activates it automatically) |
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
