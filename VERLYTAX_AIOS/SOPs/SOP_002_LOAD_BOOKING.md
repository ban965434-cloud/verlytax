# SOP 002: Load Booking
## Last Updated: 2026-03-20 | Owner: Erin

### Purpose
Define the exact process for booking a load, enforcing Iron Rules, calculating fees, and managing the load lifecycle through delivery and payment.

### Trigger
Carrier or broker submits a load for booking, or Erin identifies a load during dispatch.

---

### Steps

**Step 1 — Pre-Check (Dry Run)**
`POST /billing/load/check`
Run Iron Rules without booking. Returns pass/fail + RPM tier + violations.
Use this before committing to a load.

**Step 2 — Verify Broker is Not Blocked**
System checks `blocked_brokers` table automatically at booking.
If blocked → hard 403 reject. Never negotiate. Never rebook. (Iron Rule 8)

**Step 3 — Book Load**
`POST /billing/load/book`
All 11 Iron Rules enforced:
- Rule 1: No Florida loads (pickup OR delivery)
- Rule 2: RPM ≥ $2.51 (hard floor) | $2.51–$2.74 requires counter-offer
- Rule 3: Deadhead ≤ 50 miles AND ≤ 25% of total miles
- Rule 4: Weight ≤ 48,000 lbs
Carrier must be `status = active` or `trial`.
Fee calculated on GROSS revenue BEFORE factoring discount.

**Step 4 — RPM Tier Decision**
| Tier | RPM | Action |
|---|---|---|
| HARD_REJECT | < $2.51 | Never book |
| COUNTER_REQUIRED | $2.51–$2.74 | Counter to broker before accepting |
| ACCEPTABLE | $2.75–$2.99 | Book |
| EXCELLENT | ≥ $3.00 | Prioritize |

**Step 5 — Fee Calculation**
Fee always on GROSS load revenue BEFORE any factoring discount:
- Trial (Days 1–7): FREE
- Months 1–4 active: 8%
- Month 5+ (new carriers): 10%
- OG carriers: 8% for life
- Extra services add-on: +10% on base fee
- Minimum: $100/week
OG status stored in `carriers.is_og` — set at activation.

**Step 6 — In Transit**
Update load: `status = in_transit`.
Brain autonomous scan checks for overdue loads daily (24hr past delivery_date).

**Step 7 — Delivery Confirmation**
`POST /billing/load/{load_id}/deliver`
`status = delivered`, `pod_collected = True`.
Erin auto-SMS to carrier: "Load delivered. Fee collected Friday. Net: ${rate - fee}."

**Step 8 — Fee Collection**
`POST /billing/collect-fee/{load_id}`
Stripe charges carrier on gross revenue.
On success: `fee_collected = True`, `status = paid`.
Erin auto-SMS to carrier: "Fee cleared. BOL released. Ready for the next one?"
On failure: carrier → `suspended` immediately + Nova alert to Delta.

**Step 9 — BOL Release**
`POST /billing/load/bol-release`
Only allowed when: delivery confirmed AND fee collected.
(Iron Rule 11: Never release BOL before delivery confirmed.)

---

### Guard Rails
- Never release BOL before delivery confirmed (Iron Rule 11)
- Never release BOL before fee collected
- Fee is ALWAYS on gross revenue — never post-factoring amount
- Never book loads to/from Florida (Rule 1)
- Never book if broker is in blocked_brokers (Rule 8)
- Never book if carrier is suspended, blocked, or churned

### Escalation
- Any counter-offer negotiation that doesn't resolve: escalate to Delta
- Stripe failure on fee collection: auto-suspend + Delta alert
- Broker bad faith (refuses to pay): `POST /escalation/create` → Delta decides
