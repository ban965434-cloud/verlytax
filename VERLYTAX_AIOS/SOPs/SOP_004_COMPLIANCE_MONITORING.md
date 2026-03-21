# SOP_004 — COMPLIANCE MONITORING
**Version:** 1.0 | **Owner:** Cora (Compliance Officer) | **Built:** 2026-03-21

---

## Purpose
Ongoing compliance monitoring for all active and trial carriers.
Compliance does not end at onboarding. Cora monitors every carrier weekly
to ensure Iron Rules 5, 6, 7, 9, and 10 remain satisfied on an ongoing basis.

---

## What Cora Monitors

| Field | Source | Standard | Rule |
|---|---|---|---|
| Authority granted date | DB + FMCSA | 180+ days | Iron Rule 6/10 |
| Safety rating | DB + FMCSA | Satisfactory or None | Iron Rule 5 |
| FMCSA Clearinghouse | DB | Passed, data < 90 days old | Iron Rule 7 |
| COI expiry date | DB | Current, 31+ days remaining | N/A |
| Auto liability coverage | DB | ≥ $1,000,000 | Iron Rule implied |
| Cargo coverage | DB | ≥ $100,000 | Iron Rule implied |
| NDS enrollment | DB | Confirmed | Iron Rule 9 |

---

## Audit Frequency

- **Weekly scan** — Cora runs every Monday at 7:30 AM UTC via cron (`cora_compliance_scan`)
- **Manual audit** — Delta or Erin can trigger at any time via `POST /compliance/audit/{mc_number}`
- **Onboarding audit** — Runs at `POST /onboarding/compliance-check` (existing flow)

---

## Risk Tiers & Actions

### GREEN — No action needed
All fields pass. No SMS, no alert. Just log to ComplianceAudit.

### YELLOW — Warning
One or more fields approaching threshold (COI 31–60 days, clearinghouse 61–90 days old).
1. SMS carrier with specific deadline and exact action needed
2. Send Delta a summary report (not urgent)
3. Log to ComplianceAudit as risk_level="yellow"
4. Follow up in 7 days if no action

### RED — Critical violation
One or more Iron Rule compliance fields are violated.
1. Suspend carrier IMMEDIATELY (status → suspended)
2. Nova alert to Delta RIGHT NOW (not at end of shift, not next morning — now)
3. SMS carrier explaining suspension and what's needed to reinstate
4. Log to ComplianceAudit as risk_level="red"
5. ONLY Delta can reinstate a suspended carrier

---

## COI Expiry Timeline

| Days Remaining | Risk Level | Action |
|---|---|---|
| 61+ days | GREEN | No action |
| 31–60 days | YELLOW | SMS carrier with deadline. Delta summary. |
| 1–30 days | RED | Suspend + Delta alert immediately |
| Expired | RED | Suspend + Delta alert immediately |

---

## Insurance Minimums (Hard Floors)

- **Auto liability:** $1,000,000 minimum — no exceptions
- **Cargo coverage:** $100,000 minimum — no exceptions

If carrier is below these amounts:
- Under $1M auto or under $100K cargo → RED → suspend + Delta alert
- Missing/not on file → YELLOW → request updated COI from carrier

---

## Clearinghouse Data Age

- **0–60 days old:** GREEN — data is current
- **61–90 days old:** YELLOW — recommend re-check, but not yet a violation
- **90+ days old:** Flag for re-check. If clearinghouse_passed=False → RED.

---

## Reinstatement Protocol (RED → back to ACTIVE)

Only Delta can reinstate. Process:
1. Carrier resolves the violation (new COI submitted, clearinghouse re-run, etc.)
2. Delta reviews and confirms
3. Delta or Cora runs a fresh audit (`POST /compliance/audit/{mc_number}`)
4. If audit passes: manually set carrier status back to ACTIVE
5. Log the reinstatement in AutomationLog

---

## What Cora Does NOT Do

- Does NOT dispatch loads
- Does NOT discuss fees or billing
- Does NOT negotiate Iron Rules
- Does NOT grant exceptions to compliance requirements
- Does NOT reinstate carriers (Delta only)

---

*SOP_004 | Verlytax OS v4 | Compliance Owner: Cora*
