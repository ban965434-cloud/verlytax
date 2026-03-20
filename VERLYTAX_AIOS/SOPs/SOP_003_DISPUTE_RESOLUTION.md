# SOP 003: Dispute Resolution + Escalation
## Last Updated: 2026-03-20 | Owner: Erin (under $200) | Delta (over $500)

### Purpose
Define how disputes, payment issues, and broker bad-faith cases are handled — who decides, at what threshold, and how brokers get permanently blocked.

### Trigger
Carrier disputes a charge, broker refuses to pay, or any conflict requiring a decision.

---

### Decision Matrix

| Situation | Handler | Action |
|---|---|---|
| Money decision > $500 | Delta ONLY | Escalate immediately via Nova |
| Carrier threatening to leave | Delta ONLY | Escalate immediately |
| Billing dispute < $200 with clear evidence | Erin handles alone | Resolve, log, close |
| Dispute unresolved after 48 hours | Auto-escalate to Delta | Nova alert fires |
| Any Iron Rule violation | Hard block | Never negotiate |
| Broker bad faith (2+ issues) | Delta | Permanent block |

---

### Steps

**Step 1 — Log the Escalation**
`POST /escalation/create`
Fields: carrier_mc, load_id, issue_type, description, amount
System auto-routes: Delta (if > $500 or type in ALWAYS_ESCALATE_TYPES) or Erin.

**Step 2 — Erin Assesses (under $200 with evidence)**
Erin reviews the dispute and takes one of three actions:
- DISPUTE → DAT filing + broker flagged
- NEGOTIATE → Counter at minimum 83% of invoice
- WRITE_OFF → Write off at $500 or less

**Step 3 — Action**
`POST /escalation/dispute/action`
```json
{
  "escalation_id": 123,
  "action": "dispute" | "negotiate" | "write_off",
  "notes": "..."
}
```

**Step 4 — Dispute (DAT Filing)**
If action = `dispute`:
- File dispute on DAT
- Flag broker in system
- If 2+ issues with same broker → permanent block

**Step 5 — Negotiate (83% Floor)**
If action = `negotiate`:
- Never settle below 83% of original invoice
- Counter at 83% first; only go lower with Delta explicit approval

**Step 6 — Write-Off ($500 max)**
If action = `write_off`:
- Only allowed if amount ≤ $500
- Over $500 = hard error, must escalate to Delta

**Step 7 — Broker Permanent Block**
`POST /escalation/broker/block`
Required: broker_name, reason, dat_file (bool)
Broker written to `blocked_brokers` — never deleted, never rebooked.
Nova alert to Delta confirming block.

---

### Always-Escalate Issue Types
These ALWAYS go to Delta regardless of amount:
- `carrier_leaving`
- `legal_document`
- `new_market_launch`
- `bank_transfer_2fa`
- `ad_spend_increase`
- `bad_faith_broker_confirm`
- `unknown`

### Erin Handles Alone
These NEVER need Delta:
- `iron_rule_rejection`
- `standard_onboarding`
- `invoice_generation`
- `fee_collection_standard`
- `lead_outreach`
- `daily_report`
- `win_back`

---

### Guard Rails
- Never negotiate an Iron Rule violation — always hard block
- Never settle below 83% without Delta's explicit approval
- Never delete a blocked broker entry
- Never write off more than $500 without Delta

### Escalation
- Any unresolved dispute after 48 hours: Brain auto-escalates via Nova
- Any legal document received: immediate Delta escalation
