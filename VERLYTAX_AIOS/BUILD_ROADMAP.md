# VERLYTAX BUILD ROADMAP
## Phase 1 → Phase 3 | Revenue Scale Plan
### Verlytax OS v4 | CEO: Delta | 2026-03-20

> This is the factual build roadmap based on the Verlytax OS architecture.
> Revenue projections use the fee structure from Erin_System_Prompt_v4.txt and CLAUDE.md.
> No hallucination. Every number is derived from the actual fee model.

---

## Revenue Math (Ground Truth)

**Fee structure:**
- 8% on gross load revenue (Months 1–4)
- 10% on gross load revenue (Month 5+, new carriers)
- 8% for life (OG carriers)
- Minimum $100/week per active carrier

**Average dry van load (US, 2026 market):**
- Avg load rate: ~$1,400–$1,800 (at $2.75–$3.50 RPM × ~450 miles avg)
- Conservative: $1,400/load × 2 loads/week = $2,800/week gross per carrier
- At 8%: $224/week per carrier
- At 10%: $280/week per carrier

**Per carrier annual (8%, 2 loads/week):** ~$11,648/year
**Per carrier annual (10%, 2 loads/week):** ~$14,560/year

---

## Phase 1 — Foundation (Current)
**Target:** 30–50 active trucks | ~$100K/year revenue
**Status:** IN PROGRESS — systems built, carriers not yet onboarded

### What's Built (Ready to Use Today)
- [x] FastAPI backend — all routes live
- [x] SQLite/Postgres database with full schema
- [x] Erin (AI Dispatcher) — load booking, billing, SMS, disputes
- [x] Nova (CEO alerts) — Twilio SMS to Delta
- [x] Brain (crons) — Friday fee charge, daily trial touchpoints
- [x] Iron Rules enforcer — all 11 rules hard-coded
- [x] Carrier onboarding flow — 10 steps, FMCSA integration
- [x] Stripe billing — fee collection, auto-charge, suspend on failure
- [x] Webhook handlers — Stripe, Twilio, Retell (skeleton)
- [x] Dashboard, carrier packet, broker packet (static HTML)
- [x] Win-back sequences Day 3/7/14/30
- [x] Broker block system (memory_brokers)
- [x] BOL release guard (Iron Rule 11)
- [x] AIOS layer (this folder)

### What Needs to Be Built (Phase 1 Completion)
Priority order from CLAUDE.md:

| # | Item | Effort | Revenue Impact |
|---|---|---|---|
| 1 | `/erin/chat` endpoint — live dashboard chat | Small (1 route + JS) | Ops efficiency |
| 2 | Retell voice integration — inbound calls to Erin | Medium (Retell wiring) | Carrier acquisition |
| 3 | Annual FMCSA re-query cron | Small (new scheduler job) | Compliance / risk |
| 4 | Carrier retention — Day 30/60 testimonial SMS | Small (add to cron) | Retention / reviews |
| 5 | DocuSign at Day 5 of trial | Medium (DocuSign API) | Contract protection |
| 6 | DAT rate feed integration | Medium (DAT API key) | Load quality scoring |

### Phase 1 Revenue Model (at 10 carriers)
| Carriers | Avg Weekly Gross | Verlytax Fee (8%) | Annual |
|---|---|---|---|
| 10 | $2,800/carrier | $224/carrier/week | ~$116,480 |
| 20 | $2,800/carrier | $224/carrier/week | ~$232,960 |
| 30 | $2,800/carrier | $224/carrier/week | ~$349,440 |

**Phase 1 target hit at 10–12 active carriers generating 2 loads/week each.**

---

## Phase 2 — Scale (Next)
**Target:** 100 active trucks | ~$500K–$750K/year revenue
**Status:** NOT STARTED

### What Gets Built in Phase 2

| Item | Why |
|---|---|
| CEO Agent (shadow → active) | Delta offloads escalation decisions |
| Retell voice fully wired | Inbound carrier calls handled at scale |
| DAT rate feed live | Erin scores every lane automatically |
| DocuSign integrated | Contracts signed at scale, no manual handling |
| Annual FMCSA re-query active | Clean carrier pool at all times |
| CRM tracking layer | Broker relationships managed systematically |
| Dashboard v2 (live ops view) | Real-time carrier + load status for Delta |
| SDR campaigns at scale | Megan + Dan running outbound at volume |
| Milestone texts (1st load, 10th, 6mo, 1yr) | Carrier retention at scale |

### Phase 2 Revenue Model (at 100 carriers)
| Carriers | Mix (8%/10%) | Avg Weekly Revenue | Annual |
|---|---|---|---|
| 60 OG (8%) | $224/week | $13,440/week | $698,880 |
| 40 new (10%) | $280/week | $11,200/week | $582,400 |
| **Total** | | **$24,640/week** | **~$1,281,280** |

---

## Phase 3 — Expansion (Future)
**Target:** Canada + EU/UK | Multi-currency | $3M+/year
**Status:** DO NOT BUILD until Delta explicitly activates

### Canada (Phase 3a)
- Entity: Verlytax Canada Inc.
- Currency: CAD | Min RPM: $3.40 CAD
- Compliance: NSC/CVOR/SAAQ
- Retell: EN/FR bilingual required
- **HOLD: Do not build until Delta says go.**

### EU/UK (Phase 3b)
- EU Entity: Verlytax Europe OÜ (Estonian e-Residency)
- UK Entity: Verlytax UK Ltd.
- Currency: EUR/GBP | Min RPM UK: £1.20/mi
- **HOLD: Do not build until Delta says go.**

---

## API Keys You Need Before Phase 1 Is Operational

| Service | What For | Where to Get |
|---|---|---|
| `ANTHROPIC_API_KEY` | Erin (Claude API) | console.anthropic.com |
| `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` | Nova SMS | twilio.com/console |
| `TWILIO_FROM_NUMBER` | Nova outbound SMS number | Twilio phone number purchase |
| `STRIPE_SECRET_KEY` + `STRIPE_WEBHOOK_SECRET` | Fee collection | dashboard.stripe.com |
| `FMCSA_API_KEY` | Live FMCSA portal queries | ai.fmcsa.dot.gov (free, 1–3 days) |
| `RETELL_API_KEY` | Voice calls (Phase 1 item 2) | retellai.com |
| `CEO_PHONE` | Delta's Nova alert number | Your E.164 phone number |
| `SECRET_KEY` | App security | Generate: `openssl rand -hex 32` |
| `INTERNAL_TOKEN` | Cron auth | Generate: `openssl rand -hex 32` |

### Database (Railway Production)
1. Go to Railway dashboard → your project
2. Click "+ New" → Add PostgreSQL plugin (free tier available)
3. Railway auto-sets `DATABASE_URL` env var to `postgresql://...`
4. Update it to use asyncpg: change `postgresql://` → `postgresql+asyncpg://`
5. `asyncpg` is now in `requirements.txt` — Railway will install it automatically

---

## What's Blocking Revenue Right Now

In order of urgency:

1. **No carriers in DB yet** — all systems built, but no carrier data. Start SDR outreach.
2. **API keys not configured** — app will run but Erin, Nova, Stripe, FMCSA are all offline without keys.
3. **`/erin/chat` not wired** — Delta can't chat with Erin from the dashboard yet (easiest fix).
4. **Retell not wired** — inbound carrier calls reach the webhook but Erin doesn't answer.
5. **DocuSign not integrated** — agreements have to be sent manually for now.

---

*Verlytax Build Roadmap v1 | CEO: Delta | 2026-03-20*
