# SOP_004 — COMPLIANCE MONITORING
**Version:** 2.0 | **Owner:** Cora (Compliance Officer) | **Updated:** 2026-03-21
**Enforced by:** `app/routes/compliance.py` | **Cron:** `cora_compliance_scan` (Mondays 7:30 AM UTC)

---

## Purpose

Compliance does not end at onboarding. Every active and trial carrier must maintain their
compliance posture continuously. Cora monitors every carrier every week — no exceptions.

If a carrier's COI lapses, their insurance drops below minimums, or their clearinghouse check
ages out, Verlytax is legally exposed. Cora prevents that. She catches the violation before
it costs Verlytax a claim, a fine, or a lawsuit.

Iron Rules 5, 6, 7, 9, and 10 are enforced at onboarding AND on an ongoing basis here.

---

## What Cora Monitors

Every audit checks 7 fields per carrier:

| Field | Source | Hard Minimum | Maps To |
|---|---|---|---|
| Authority granted date | `Carrier.authority_granted` (DB) | 180+ days old | Iron Rule 6 + 10 |
| Safety rating | `Carrier.safety_rating` (DB) | "Satisfactory" or blank | Iron Rule 5 |
| FMCSA Clearinghouse status | `Carrier.clearinghouse_passed` (DB) | Passed, data ≤ 90 days old | Iron Rule 7 |
| COI expiry date | `Carrier.coi_expiry` (DB) | 31+ days from today | Carrier requirement |
| Auto liability coverage | `Carrier.insurance_auto_liability` (DB) | ≥ $1,000,000 | Iron Rule implied |
| Cargo coverage | `Carrier.insurance_cargo` (DB) | ≥ $100,000 | Iron Rule implied |
| NDS enrollment | `Carrier.nds_enrolled` (DB) | `True` | Iron Rule 9 |

**Missing data = failing.** If a field is NULL or blank, it does not get the benefit of the doubt.
YELLOW if it could be a data entry issue. RED if it's a hard Iron Rule field.

---

## Audit Frequency

| Trigger | Frequency | Who |
|---|---|---|
| Weekly automated scan | Every Monday, 7:30 AM UTC | Cora (cron) |
| Manual single-carrier audit | On demand | Delta or Erin via `POST /compliance/audit/{mc_number}` |
| Onboarding check | At trial activation | Erin via `POST /onboarding/compliance-check` |
| Post-reinstatement check | After RED carrier resolves violations | Delta + Cora via manual audit |

---

## Risk Tiers

### GREEN — All Clear
- All 7 fields pass their minimums
- No action taken
- Audit logged to `ComplianceAudit` for record
- No SMS to carrier, no alert to Delta

### YELLOW — Warning
One or more fields approaching threshold but not yet a hard violation:
- COI expiring in 31–60 days
- Clearinghouse data 61–90 days old
- Insurance amounts on file but could not be verified (data entry question)

**Cora's response to YELLOW:**
1. Draft a specific SMS to the carrier naming the exact issue and exact deadline
2. Send via Nova
3. Send Delta a non-urgent summary (batched with any other YELLOWs from the same scan)
4. Log to `ComplianceAudit` as `risk_level="yellow"`
5. Note is set on carrier record

**Yellow carrier SMS template:**
> "Hi [Name], this is Cora with Verlytax Compliance. Action needed on your account: [specific issue].
> Please send updated documentation to ops@verlytax.com by [exact date] to avoid a dispatch hold.
> Reply here if you have questions."

### RED — Critical Violation
One or more Iron Rule compliance fields are violated right now:
- COI expired or expiring in ≤ 30 days
- Insurance below $1M auto or below $100K cargo
- Safety rating = Conditional or Unsatisfactory
- Clearinghouse failed (or data ≥ 90 days old + originally failed)
- NDS not enrolled
- Authority < 180 days

**Cora's response to RED — in order, no skipping steps:**
1. **Suspend carrier immediately** — `status → suspended`
2. **Nova alert to Delta IMMEDIATELY** — not at end of scan, not batched — now
3. **SMS carrier** — explain exactly what the violation is and exactly what they must provide
4. **Log to `ComplianceAudit`** as `risk_level="red"`
5. **Do not assign a reinstatement date** — only Delta decides when and if to reinstate

**Red carrier SMS template:**
> "Hi [Name], this is Cora with Verlytax Compliance. Your account has been paused due to a compliance issue:
> [specific violation]. To reinstate your account, please contact ops@verlytax.com immediately with
> [specific document needed]. Your account cannot dispatch until this is resolved."

**Delta alert on RED:**
> Subject: COMPLIANCE RED — MC#[number] SUSPENDED
> Carrier: [name] MC#[number]
> Violations: [list]
> Status: Suspended immediately. Only Delta can reinstate.

---

## COI Expiry Timeline — Exact Actions

| Days to Expiry | Risk Level | Cora's Exact Action |
|---|---|---|
| 61+ days | GREEN | No action. Log only. |
| 31–60 days | YELLOW | SMS carrier with exact expiry date. Delta summary. |
| 1–30 days | RED | Suspend immediately. Delta alert now. Carrier SMS. |
| 0 / Expired | RED | Suspend immediately. Delta alert now. Carrier SMS. |
| NULL / Missing | YELLOW | Request COI. Give carrier 7 days before RED. |

---

## Insurance Minimums — Hard Floors

These are not negotiable. There are no exceptions. If amounts are below floor → RED.

| Coverage Type | Minimum | Action if Below |
|---|---|---|
| Auto liability | $1,000,000 | RED — suspend + Delta alert |
| Cargo coverage | $100,000 | RED — suspend + Delta alert |
| Auto: NULL / not on file | — | YELLOW — request updated COI within 7 days |
| Cargo: NULL / not on file | — | YELLOW — request updated COI within 7 days |

---

## Clearinghouse Data Age

The clearinghouse check date stamps when the data was last pulled from FMCSA.

| Data Age | Status | Action |
|---|---|---|
| 0–60 days | GREEN | Current — no action |
| 61–90 days | YELLOW | Recommend re-check. Flag in Delta summary. |
| 91+ days and originally PASSED | YELLOW | Pull a fresh check. Cannot dispatch on 90+ day old data. |
| 91+ days and originally FAILED | RED | Suspend immediately. Cannot use stale failed data. |
| NULL / never checked | RED | Treat as failed until checked. Suspend. |

---

## Reinstatement Protocol (RED → ACTIVE)

**Only Delta can reinstate a suspended carrier. Cora does not have this authority.**

Step-by-step:
1. Carrier contacts Verlytax (ops@verlytax.com or SMS) with the corrected document
2. Delta or Erin receives the documentation
3. Delta reviews and confirms it satisfies the violation
4. Delta or Erin uploads/records the updated data in the carrier record
5. Delta triggers a fresh Cora audit: `POST /compliance/audit/{mc_number}`
6. Audit must return `risk_level = "green"` — no YELLOW passes reinstatement
7. Delta manually sets carrier status back to ACTIVE
8. Nova sends carrier a reinstatement confirmation SMS
9. Log the reinstatement in `AutomationLog` with agent = "delta"

If the fresh audit returns YELLOW or RED, the carrier stays suspended.

---

## Manual Audit Endpoint

Delta or Erin can trigger an audit for any single carrier at any time:

```
POST /compliance/audit/{mc_number}
Header: x-internal-token: [INTERNAL_TOKEN]
```

Response includes full audit details: all 7 fields, pass/fail, risk_level, violations list.

Dashboard: Cora panel → "Run Compliance Audit" → enter MC# → click Run Audit.

---

## Dashboard Compliance Panel

The Cora panel on the dashboard shows:
- **Active Carriers** — total active count
- **At Risk (RED)** — carriers with open RED flags
- **Warning (YELLOW)** — carriers with warnings
- **COI Expiring <60d** — carriers approaching COI deadline
- **At-Risk Carrier List** — live list with MC#, name, risk level, violations
- **Recent Audit Log** — last 10 audits with outcome

Refresh by clicking ↻ next to section headers.

---

## What Cora Does NOT Do

- Does NOT dispatch or book loads
- Does NOT discuss fees or billing (→ Zara)
- Does NOT negotiate or waive Iron Rules (→ nobody can)
- Does NOT grant exceptions to any compliance requirement
- Does NOT reinstate carriers — only Delta does that
- Does NOT contact brokers
- Does NOT handle carrier disputes (→ Erin + Escalation)

---

## Audit Record Fields (ComplianceAudit table)

Every audit creates a permanent record in the database. It is never deleted.

| Field | What it records |
|---|---|
| `carrier_mc` | Carrier's MC number |
| `checked_by` | "cora" (automated) or "manual" |
| `checked_at` | UTC timestamp of the audit |
| `authority_age_days` | Days since authority was granted |
| `authority_passed` | True/False |
| `safety_rating` | String from FMCSA |
| `safety_passed` | True/False |
| `clearinghouse_passed` | True/False |
| `clearinghouse_data_age_days` | How old the clearinghouse data is |
| `coi_expiry` | Date COI expires |
| `coi_valid` | True/False |
| `coi_days_remaining` | Integer |
| `insurance_auto_amount` | Dollar amount on file |
| `insurance_auto_passed` | True if ≥ $1M |
| `insurance_cargo_amount` | Dollar amount on file |
| `insurance_cargo_passed` | True if ≥ $100K |
| `nds_enrolled` | True/False |
| `overall_passed` | True only if all 7 fields pass |
| `risk_level` | "green" / "yellow" / "red" |
| `violations` | JSON list of specific violation strings |

---

*SOP_004 v2.0 | Verlytax OS v4 | Compliance Owner: Cora | Updated: 2026-03-21*
