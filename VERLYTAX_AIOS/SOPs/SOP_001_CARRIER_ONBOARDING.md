# SOP 001: Carrier Onboarding
## Last Updated: 2026-03-20 | Owner: Erin + Brain

### Purpose
Define the exact 10-step process to take a carrier from cold lead to active paying client.

### Trigger
New carrier expresses interest (inbound call, SMS, Receptionist agent, or manual entry).

---

### Steps

**Step 1 — Create Lead**
`POST /onboarding/lead`
Required: mc_number, name, phone, email
Optional: dot_number, ein, truck_type, authority_granted_date, factoring_company
Carrier enters DB with `status = lead`.

**Step 2 — FMCSA Live Lookup**
`POST /onboarding/fmcsa-lookup?mc_number={mc}`
Pull safety_rating, authority_granted_date, clearinghouse status directly from FMCSA SAFER portal.
Never accept self-reported data (Iron Rule 10).

**Step 3 — Compliance Check (Iron Rules 5–9)**
`POST /onboarding/compliance-check`
Brain runs all carrier Iron Rules:
- Safety rating must be Satisfactory or None (Rule 5)
- Authority 180+ days old (Rules 6 + 10)
- FMCSA Clearinghouse passed (Rule 7)
- NDS enrolled (Rule 9)
- Carrier not blocked (Rule 8)
FAIL → carrier blocked immediately + Nova alert to Delta.
PASS → carrier moves to `status = trial`.

**Step 4 — Activate Trial**
`POST /onboarding/activate-trial?mc_number={mc}`
Brain creates Google Drive folder structure.
Nova sends Day 1 carrier packet SMS.
7-day free trial begins.

**Step 5 — Day 3 Check-In (auto)**
Brain cron fires Day 3 SMS via Nova: "How's everything going?"

**Step 6 — Day 5 — DocuSign (not yet built)**
Service agreement sent via DocuSign. (Roadmap item 5.)

**Step 7 — Day 7 — Convert Offer (auto)**
Brain cron fires Day 7 SMS: "Trial ends today — reply YES to go active."
Carrier replies YES → Delta manually converts or Erin handles.

**Step 8 — Convert to Active**
`POST /onboarding/convert?mc_number={mc}&stripe_customer_id={id}`
Stripe customer attached.
`status = active`, `active_since = now`.
Nova alerts Delta: "New Carrier Converted."

**Step 9 — First Load**
`POST /billing/load/book`
All 11 Iron Rules enforced before booking.
NDS enrollment must be confirmed (Rule 9).

**Step 10 — Ongoing (auto)**
Friday auto-charge via Stripe.
Day 30 and Day 60 retention SMS via Brain testimonial cron.
Annual FMCSA re-check via Brain annual cron.

---

### Guard Rails
- Never skip compliance check (Iron Rules 5–9)
- Never accept self-reported authority date — always pull from FMCSA portal (Rule 10)
- Never dispatch a load before NDS enrollment confirmed (Rule 9)
- Never block a carrier without Nova alert to Delta

### Escalation
- Any carrier who fails compliance: Delta gets Nova alert immediately
- Any carrier threatening to leave during trial: escalate to Delta (never negotiate alone)
