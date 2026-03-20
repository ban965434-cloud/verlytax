# KENNETH — DISPATCH MODULE
## Isolated Carrier Profile | Verlytax OS v4
### CEO: Delta | Last Updated: [FILL IN DATE WHEN ONBOARDED]

> This is Kenneth's isolated carrier file.
> All of Kenneth's specific dispatch preferences, lane history, notes, and operating rules
> live here and in verlytax.db.
> When Erin dispatches Kenneth, she reads this file first.
>
> **IMPORTANT:** Fields marked [FILL IN] are placeholders.
> Delta must complete these before Kenneth's first dispatch.

---

## Identity

| Field | Value |
|---|---|
| **Name** | Kenneth [FILL IN LAST NAME] |
| **MC Number** | [FILL IN] |
| **DOT Number** | [FILL IN] |
| **Phone** | [FILL IN — E.164 format e.g. +12125551234] |
| **Email** | [FILL IN] |
| **Home Base** | [FILL IN — City, State] |
| **Status** | [lead / trial / active — FILL IN] |
| **Trial Start** | [FILL IN DATE] |
| **Active Since** | [FILL IN DATE or leave blank if trial] |
| **OG Carrier?** | [YES / NO — if YES, fee is 8% for life] |

---

## Equipment

| Field | Value |
|---|---|
| **Truck Type** | Dry van 53ft |
| **Truck Year** | [FILL IN] |
| **VIN** | [FILL IN] |
| **Plate** | [FILL IN — State + number] |
| **EIN** | [FILL IN — verified against MC registration] |

---

## Compliance Status

| Check | Status | Date Verified |
|---|---|---|
| FMCSA Authority | [ACTIVE / FILL IN] | [FILL IN] |
| Authority Age | [FILL IN days] — must be 180+ | [FILL IN] |
| Safety Rating | [FILL IN — must not be Unsatisfactory or Conditional] | [FILL IN] |
| Clearinghouse | [PASSED / FAILED / PENDING] | [FILL IN] |
| NDS Enrollment | [YES / NO / PENDING] | [FILL IN] |
| COI Expiry | [FILL IN DATE] | [FILL IN] |
| Auto Liability | $[FILL IN — must be $1M+] | [FILL IN] |
| Cargo Coverage | $[FILL IN — must be $100K+] | [FILL IN] |
| W-9 on File | [YES / NO] | [FILL IN] |
| DocuSign Signed | [YES / NO] | [FILL IN] |
| CDL Class | [FILL IN — must match equipment] | [FILL IN] |
| Medical Cert | [FILL IN — must be current] | [FILL IN] |

**⚠ Do not dispatch Kenneth until all compliance fields are green.**

---

## Factoring

| Field | Value |
|---|---|
| **Factoring Company** | [FILL IN — OTR Solutions / RTS Financial / Triumph / TBS / None] |
| **Remittance Address** | [FILL IN — if factoring, payment goes HERE not to Kenneth directly] |
| **Factoring Rate** | [FILL IN — e.g. 3% discount] |

---

## Billing

| Field | Value |
|---|---|
| **Stripe Customer ID** | [FILL IN — after Stripe activation] |
| **Stripe Payment Method** | [FILL IN — card last 4] |
| **Fee Tier** | [8% / 10% / 8% OG for life — FILL IN] |
| **Extra Services?** | [YES / NO — +10% if YES] |
| **Weekly Minimum** | $100 |

---

## Lane Preferences & Operating Rules

**Home Base:** [FILL IN — City, State]

**Preferred Lanes:**
1. [FILL IN — e.g. "Chicago to East Coast"]
2. [FILL IN]
3. [FILL IN]

**Lanes to Avoid:**
1. [FILL IN — e.g. "Rural Midwest outbound"]
2. [FILL IN]

**Max Deadhead Willing to Run:** [FILL IN — must be ≤ 50mi / 25%]

**Preferred Pickup Days:** [FILL IN — e.g. "Mon–Wed preferred, no Sunday pickups"]

**Min Rate Kenneth Will Accept:** $[FILL IN per mile — must be ≥ $2.51]

**Load Type Preferences:** General freight / auto parts / consumer goods / dry goods

**Delivery Appointment Type:** [FILL IN — prefers FCFS / appointment / either]

---

## Communication Preferences

| Field | Value |
|---|---|
| **Preferred Contact** | [Text / Call / Either] |
| **Best Hours to Reach** | [FILL IN — e.g. "6 AM – 8 PM ET"] |
| **Language** | [English / FILL IN if other] |
| **Check-in Frequency** | Every 2–4 hours on active loads (standard) |

---

## Load History

| Load ID | Route | RPM | Date | Status | Notes |
|---|---|---|---|---|---|
| — | — | — | — | — | No loads yet |

*Populated automatically from verlytax.db as loads are booked.*

---

## Escalation Notes

| Date | Issue | Resolution | Resolved By |
|---|---|---|---|
| — | — | — | — |

*Populated from escalation_logs in verlytax.db.*

---

## Special Notes from Delta

[FILL IN — any specific instructions, agreements, or history with Kenneth that Erin needs to know]

Examples:
- "Kenneth prefers short calls — text first."
- "Kenneth has OG status — confirmed by Delta on [date]. 8% for life."
- "Kenneth's wife handles paperwork — copy her at [email]."

---

## Erin's Standing Instructions for Kenneth

When dispatching Kenneth:
1. Check this file before every load booking.
2. Confirm lanes match his preferences before accepting any load.
3. Text him load details — don't call unless he doesn't respond within 1 hour.
4. Check HOS before every dispatch: "Hey Kenneth, how many hours you got?"
5. Kenneth gets [FILL IN priority level: standard / priority] load search.
6. If Kenneth raises any issue → log in escalation_logs → follow Decision Engine stage.

---

## Onboarding Checklist for Kenneth

- [ ] Delta confirms Kenneth's MC number and OG status
- [ ] Brain runs FMCSA compliance check (`POST /onboarding/compliance-check`)
- [ ] Clearinghouse query completed ($1.25)
- [ ] NDS enrollment confirmed ($100/yr — Kenneth pays)
- [ ] All compliance documents collected (W-9, COI, CDL, medical cert)
- [ ] DocuSign agreement sent (Day 5 if trial) and signed
- [ ] Stripe customer created (`POST /onboarding/convert`)
- [ ] Trial activated (`POST /onboarding/activate-trial`)
- [ ] Day 1 packet sent via Nova
- [ ] This file updated with all FILL IN fields

---

*Kenneth Dispatch Module v1 | Verlytax OS v4 | CEO: Delta*
*Complete all [FILL IN] fields before Kenneth's first dispatch.*
