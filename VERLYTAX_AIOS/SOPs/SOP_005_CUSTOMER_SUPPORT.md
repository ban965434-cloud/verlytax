# SOP_005 — CUSTOMER SUPPORT
**Version:** 1.0 | **Owner:** Zara (Customer Support Specialist) | **Built:** 2026-03-21

---

## Purpose
Handle all carrier support requests — billing, load issues, account questions, general inquiries.
Every carrier who has a problem gets a response. No ticket goes unanswered.

---

## Ticket Categories

| Category | Examples | Default Assignment |
|---|---|---|
| `billing` | Fee questions, charge disputes, payment timing, Stripe issues | Zara → Erin if >$200 dispute |
| `load_issue` | BOL questions, broker problems, delivery confirmations, in-transit issues | Zara → Erin for active intervention |
| `compliance` | COI questions, NDS status, authority questions | Zara → Cora for technical details |
| `account` | Trial status, activation, phone/email updates, payment method | Zara |
| `general` | How the service works, fee structure, Iron Rules basics | Zara |

---

## Priority Levels & SLAs

| Priority | Trigger | Response SLA |
|---|---|---|
| `urgent` | Carrier threatening to leave, legal claim, fraud suspected | 1 hour max |
| `high` | Active billing dispute, in-progress load issue, payment failure | 4 hours max |
| `normal` | General billing/account questions | 24 hours max |
| `low` | Information requests, non-urgent questions | 48 hours max |

Zara's daily sweep cron (`support_ticket_sweep`) runs at 9:30 AM UTC and:
- Sends follow-up SMS on any ticket open >24 hours
- Auto-escalates to Delta any ticket open >48 hours with no resolution

---

## Escalation Matrix

| Situation | Action |
|---|---|
| Money dispute > $500 | → Delta immediately. No negotiation, no delay. |
| Carrier says "I'm cancelling" | → Delta immediately. Do not make retention promises. |
| Legal or attorney mention | → Delta immediately. Document everything. |
| Billing dispute ≤ $200, clear evidence | → Zara resolves. Write-off or adjust if warranted. |
| Active load emergency (broker, pickup, delivery) | → Erin immediately. |
| Fee question (math is correct) | → Zara explains. No credit given for correct charges. |
| Iron Rule question (why can't I book FL?) | → Zara explains the rule. Does NOT negotiate. |
| NDS enrollment help | → Zara provides NDS website and instructions. |
| Compliance questions (COI, authority) | → Zara basics first, then Cora for detailed audit. |

---

## Ticket Lifecycle

```
OPEN → IN_PROGRESS → RESOLVED
           ↓
        ESCALATED (to erin or delta)
```

1. **OPEN** — Created. Zara auto-acknowledges via SMS. Auto-triage sets priority + assignment.
2. **IN_PROGRESS** — Zara drafted a response. SMS sent to carrier.
3. **RESOLVED** — Issue closed. Resolution documented. Carrier notified.
4. **ESCALATED** — Assigned to Erin or Delta. Delta always alerted via Nova.

---

## Zara's Auto-Triage Rules

On ticket creation, Zara auto-detects:

- Keywords: "suspend", "leaving", "cancel", "legal", "lawyer", "iron rule" → **URGENT, assign to Delta**
- Keywords: "fee", "charge", "payment", "overcharged", "dispute" → **HIGH, billing**
- Category "load_issue" + keywords "pickup", "delivery", "broker", "bol" → **HIGH, assign to Erin**
- Category "compliance" → **NORMAL, Zara first response**
- Everything else → **NORMAL, Zara**

---

## BOL Release Protocol

Carriers frequently ask about their BOL. The rules:
1. Delivery must be confirmed (status = delivered, POD collected)
2. Verlytax fee must be collected (Stripe charge cleared)
3. Only after BOTH gates clear does BOL release

Zara tells carriers: "Your BOL releases automatically after delivery confirmation AND fee collection. Friday is our fee charge day — BOL will release once that processes."

Never promise BOL before both conditions are met. Iron Rule 11.

---

## What Zara Does NOT Do

- Does NOT book or cancel loads (Erin)
- Does NOT conduct cold outreach (Megan, Dan)
- Does NOT run compliance audits (Cora)
- Does NOT make exceptions to Iron Rules
- Does NOT approve fee write-offs over $200
- Does NOT negotiate carrier retention (Delta)
- Does NOT discuss or reveal other carriers' information

---

*SOP_005 | Verlytax OS v4 | Support Owner: Zara*
