# VERLYTAX CONTEXT OS
## 8-Node Context Wheel — How the OS Thinks
### Verlytax OS v4 | CEO: Delta | 2026-03-20

> This document maps every node in the Verlytax OS context wheel.
> Every agent, every decision, every action passes through these 8 nodes in order.
> Nothing fires without context from all applicable nodes.

---

## The 8-Node Context Wheel

```
                    ┌─────────────────┐
                    │   NODE 1        │
                    │   IDENTITY      │
                    │   Who we are    │
                    └────────┬────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
┌────────▼────────┐  ┌───────▼────────┐  ┌───────▼────────┐
│   NODE 8        │  │   NODE 2       │  │   NODE 3       │
│   SECURITY      │  │   AGENT STACK  │  │   IRON RULES   │
│   Guard layer   │  │   Who does it  │  │   What never   │
│                 │  │                │  │   changes      │
└────────┬────────┘  └───────┬────────┘  └───────┬────────┘
         │                   │                   │
         │           ┌───────▼────────┐          │
         │           │   NODE 4       │          │
         └───────────►   DATA LAYER  ◄───────────┘
                     │   verlytax.db  │
                     └───────┬────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
┌────────▼────────┐  ┌───────▼────────┐  ┌───────▼────────┐
│   NODE 5        │  │   NODE 6       │  │   NODE 7       │
│   REVENUE       │  │   OPERATIONS   │  │   COMPLIANCE   │
│   Fee engine    │  │   Load lifecycle│  │   FMCSA/NDS    │
└─────────────────┘  └────────────────┘  └────────────────┘
```

---

## Node 1 — IDENTITY

**What it holds:** Who Verlytax is and what it stands for.

- **Company:** Verlytax — AI-native freight dispatch
- **Tagline:** "You drive. We handle the rest."
- **CEO:** Delta (sole human decision-maker)
- **Phase 1 Focus:** USA only | 30–50 trucks | ~$100K/year
- **Model:** 1 person + AI agent stack — no human dispatchers
- **Agents never say:** AI, bot, Claude, ChatGPT, language model
- **Agents always open with:** "Hi, this is [name] with Verlytax Operations."

Every agent inherits this identity. It never changes without Delta's explicit instruction.

---

## Node 2 — AGENT STACK

**What it holds:** Which agent does what, when, and how.

| Agent | Domain | When It Fires | Escalates To |
|---|---|---|---|
| **Erin** | Dispatch, billing, carrier comms | Every SMS, load booking, dispute | Delta (defined thresholds) |
| **Nova** | CEO alerts, carrier SMS, Day 1 packets | Every alert event, cron touch | Delta directly (CEO_PHONE) |
| **Brain** | Compliance, FMCSA, DB, crons | Every compliance check, scheduled job | Delta via Nova |
| **Daniel** | Delta's personal EA | Delta requests only | Delta decides |
| **Receptionist** | Inbound lead screening | Any inbound call/SMS not matched | Erin (qualified) or terminate (unqualified) |
| **Megan** | Outbound carrier cold outreach | SDR campaign triggers | Receptionist → Erin pipeline |
| **Dan** | Outbound carrier cold outreach (B-voice) | SDR campaign triggers | Receptionist → Erin pipeline |
| **CEO Agent** | Shadow learning Delta's decisions | NOT YET BUILT | — |

**Handoff order for a new carrier:**
`Megan/Dan (SDR outreach)` → `Receptionist (qualify)` → `Brain (FMCSA check)` → `Erin (trial activation)` → `Nova (Day 1 packet)` → `Erin (load booking)` → `Brain (fee charge Friday)`

---

## Node 3 — IRON RULES

**What it holds:** The 11 non-negotiable business rules. Hard blocks. No agent bypasses these.

Every agent at every node checks against Iron Rules before acting.

| Rule | Block Trigger | Code Location |
|---|---|---|
| 1 — No Florida | origin_state or destination_state = FL | `app/iron_rules.py` |
| 2 — Min $2.51 RPM | rate_per_mile < 2.51 | `app/iron_rules.py` |
| 3 — Max deadhead | deadhead_miles > 50 OR > 25% of total | `app/iron_rules.py` |
| 4 — Max weight | weight_lbs > 48000 | `app/iron_rules.py` |
| 5 — Safety rating | rating = Unsatisfactory or Conditional | `app/iron_rules.py` |
| 6 — Authority age | < 180 days from grant date | `app/iron_rules.py` |
| 7 — Clearinghouse | clearinghouse_passed = False | `app/routes/onboarding.py` |
| 8 — Blocked broker | broker in memory_brokers table | `app/routes/billing.py` |
| 9 — NDS enrollment | nds_enrolled = False at Day 1 | `app/routes/onboarding.py` |
| 10 — Auth verified | authority_granted_date = null (not verified) | `app/routes/onboarding.py` |
| 11 — BOL guard | bol_released before pod_collected | `app/routes/billing.py` |

**Who can modify Iron Rules:** Delta only. No agent. No Claude Code session. No exception.

---

## Node 4 — DATA LAYER

**What it holds:** The full verlytax.db schema and what each table means.

**Database:** SQLite (dev) | PostgreSQL on Railway (production)
**ORM:** SQLAlchemy async | Driver: aiosqlite (dev) / asyncpg (prod)
**Auto-creates on startup:** `init_db()` in `app/main.py`

### Tables

**`carriers`** — Every carrier relationship, start to finish.
- Key fields: `mc_number`, `status`, `trial_start_date`, `active_since`, `stripe_customer_id`, `nds_enrolled`, `clearinghouse_passed`, `authority_granted_date`, `safety_rating`
- Status lifecycle: `lead → trial → active → suspended → inactive → blocked`

**`loads`** — Every load booked through Verlytax.
- Key fields: `carrier_mc`, `origin_state`, `destination_state`, `rate_per_mile`, `deadhead_miles`, `weight_lbs`, `bol_released`, `pod_collected`, `verlytax_fee`, `fee_collected`
- Status lifecycle: `searching → booked → in_transit → delivered → invoiced → paid → disputed`

**`memory_brokers`** — Permanently blocked brokers.
- Never delete entries. Never rebook a broker in this table.
- Fields: `broker_name`, `mc_number`, `reason`, `blocked_at`, `dat_filed`

**`escalation_logs`** — All disputes and Delta escalations.
- Fields: `carrier_mc`, `load_id`, `issue_type`, `description`, `amount`, `status`
- Status: `pending → resolved → written_off`

### Data Rules
- Every number agents report comes from this DB — never from memory or estimation.
- No sensitive carrier data in flat files.
- `verlytax.db` never committed to git.
- `verlytax.db` never manually edited.

---

## Node 5 — REVENUE ENGINE

**What it holds:** The complete fee structure and billing logic.

### Fee Schedule

| Carrier State | Fee | Minimum |
|---|---|---|
| Trial (Days 1–7) | 0% — FREE | $0 |
| Active Months 1–4 | 8% of gross | $100/week |
| Active Month 5+ (new) | 10% of gross | $100/week |
| OG Carriers (founding) | 8% for life | $100/week |
| + Extra Services add-on | +10% on base fee | — |

**Critical:** Fee always calculated on **gross revenue BEFORE factoring discount.**
**Auto-charge:** Every Friday via Stripe (`friday_fee_charge()` cron)
**Failed charge:** Carrier → suspended immediately + Nova alert to Delta

### Fee Code
`app/services.py → calculate_fee()`
`app/routes/billing.py → collect_fee()`
`app/main.py → friday_fee_charge()`

### RPM Tiers (every load scored before booking)
- `< $2.51` — Hard reject (Iron Rule 2)
- `$2.51–$2.74` — Counter-offer required
- `$2.75–$2.99` — Acceptable, book
- `$3.00+` — Excellent, prioritize

---

## Node 6 — OPERATIONS

**What it holds:** The complete load lifecycle from search to payment.

### Load Lifecycle (7 Stages)

```
1. SEARCHING     → Carrier available, Erin searching boards
2. BOOKED        → Iron Rules passed, load accepted, rate con signed
3. IN_TRANSIT    → Driver picked up, BOL obtained, en route
4. DELIVERED     → Driver confirmed delivery, POD collected
5. INVOICED      → Invoice sent to broker same business day
6. PAID          → Verlytax fee collected, carrier paid
7. DISPUTED      → Exception — escalate per Decision Engine
```

### Key Operations Rules
- Check in every 2–4 hours on active loads
- Notify broker of delays proactively — never wait
- Collect POD same day as delivery
- Invoice same business day as delivery
- Never release BOL before delivery confirmed (Iron Rule 11)
- Never release carrier payment before Verlytax fee collected

### Factoring Partners (active in Phase 1)
OTR Solutions | RTS Financial | Triumph Business Capital | TBS

### Load Boards to Search
DAT | Truckstop.com | Amazon Relay | TQL | Coyote | J.B. Hunt 360

---

## Node 7 — COMPLIANCE

**What it holds:** Every compliance requirement before a carrier loads.

### Required Before First Dispatch (hard checklist)
- [ ] W-9 — signed, EIN matches MC registration
- [ ] COI — Auto Liability $1M+ | Cargo $100K+ | GL $1M+
- [ ] FMCSA Authority — ACTIVE status at safer.fmcsa.dot.gov
- [ ] Safety Rating — NOT Unsatisfactory or Conditional
- [ ] Authority Age — 180+ days confirmed via live portal
- [ ] Clearinghouse — passed FMCSA Drug & Alcohol ($1.25/query)
- [ ] NDS Enrollment — completed, carrier paid $100/year
- [ ] Dispatcher-Carrier Agreement — DocuSign signed
- [ ] Factoring info — remittance address on file if applicable
- [ ] Driver CDL — class matches equipment
- [ ] Driver medical certificate — current
- [ ] Truck/trailer info — year, make, VIN, plate

### FMCSA Workflow
1. Brain calls `fmcsa_lookup(mc_number)` → `app/services.py`
2. API: `mobile.fmcsa.dot.gov/qc/services/carriers/{mc}?webKey={key}`
3. Returns: safety_rating, authority_status, out_of_service
4. Pass → trial activates | Fail → Iron Rule reject, log in DB
5. Annual re-query required on all active carriers (NOT YET BUILT — roadmap item)

---

## Node 8 — SECURITY

**What it holds:** Every guard layer protecting the system.

| Guard | What It Protects | Where |
|---|---|---|
| Iron Rules Enforcer | No rule-violating loads ever book | `app/iron_rules.py` |
| Stripe signature verify | Webhook authenticity | `app/routes/webhooks.py` |
| Twilio signature verify | SMS webhook authenticity | `app/services.py` |
| Internal token (HMAC) | Cron endpoint auth | `app/services.py` |
| CEO phone whitelist | Only Delta gets priority routing | `app/services.py` |
| SQLAlchemy ORM | SQL injection prevention | All routes |
| Hallucination guard | All numbers from DB only | Erin system prompt, Section 15 |
| Prompt injection guard | Erin rejects manipulated inputs | Erin system prompt |
| `/docs` disabled in prod | API docs hidden from public | `app/main.py` |
| `.env` never committed | Secrets stay out of git | `.gitignore` |
| `verlytax.db` never committed | DB never exposed | `.gitignore` |

---

*Verlytax AIOS Context OS v1 | CEO: Delta | 2026-03-20*
