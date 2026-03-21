# SOP_005 — CUSTOMER SUPPORT
**Version:** 2.0 | **Owner:** Zara (Customer Support Specialist) | **Updated:** 2026-03-21
**Enforced by:** `app/routes/support.py` | **Cron:** `support_ticket_sweep` (Daily 9:30 AM UTC)

---

## Purpose

Every carrier who has a problem gets a response. No ticket goes unanswered. No ticket gets deleted.

Tickets are permanent records. They resolve, escalate to Erin, escalate to Delta, or escalate to
a live voice agent via Retell — but they never disappear. Every interaction is logged.

Zara's job is to close tickets fast, at the right level, without bothering Delta unless necessary.

---

## Ticket Categories

| Category | What It Covers | Default Handler |
|---|---|---|
| `billing` | Weekly fee questions, charge disputes, Stripe payment issues, fee math explanations | Zara → Erin if >$200 active dispute |
| `load_issue` | BOL status, broker problems, pickup/delivery confirmations, in-transit issues, POD questions | Zara → Erin for any active intervention |
| `compliance` | COI questions, NDS enrollment status, authority questions, insurance questions | Zara first response → Cora for technical audit |
| `account` | Trial status, activation, phone/email/address updates, payment method changes | Zara |
| `general` | How the service works, fee structure, Iron Rules explanations, onboarding questions | Zara |

---

## Priority Levels and SLAs

| Priority | When It's Set | Response SLA | Who It Goes To |
|---|---|---|---|
| `urgent` | Carrier threatens to leave / mentions legal / says "cancel" / "lawyer" / "iron rule" dispute | 1 hour | Delta immediately |
| `high` | Active billing dispute, payment failure, in-progress load issue | 4 hours | Erin (loads) or Zara (billing) |
| `normal` | General billing, account, compliance questions | 24 hours | Zara |
| `low` | Information requests, non-urgent questions | 48 hours | Zara |

**The `support_ticket_sweep` cron (daily 9:30 AM UTC):**
- Sends Zara follow-up SMS to carriers on any ticket open > 24 hours
- Auto-escalates to Delta any ticket open > 48 hours with no resolution

---

## Ticket Lifecycle

```
OPEN
  │
  ├──► IN_PROGRESS  (Zara drafted response, SMS sent)
  │         │
  │         ├──► RESOLVED  (issue closed, resolution logged, carrier notified)
  │         │
  │         └──► ESCALATED  ──► assigned_to: erin | delta | voice_agent
  │
  └──► ESCALATED (skipped to escalation — urgent or auto-sweep)
```

**Rules:**
- Tickets are NEVER deleted from the database
- Every ticket has a permanent audit trail in `AutomationLog`
- A ticket stays OPEN until it is explicitly resolved or escalated
- RESOLVED means Delta or Erin confirmed the issue is closed
- ESCALATED to voice_agent means a Retell call was placed to the carrier

---

## Zara's Auto-Triage on Ticket Creation

When a ticket is created, Zara reads the subject + description and automatically sets priority
and assignment. This happens instantly — no delay.

| Keyword Detected | Priority Set | Assigned To | Why |
|---|---|---|---|
| "suspend", "leaving", "cancel", "legal", "lawyer", "irs", "iron rule" | `urgent` | delta | Carrier threatening or legal claim — Delta only |
| "fee", "charge", "payment", "stripe", "overcharged", "dispute" | `high` | erin (if billing) or zara | Money dispute — fast response required |
| category = `load_issue` + "pickup", "delivery", "broker", "bol" | `high` | erin | Active load — Erin must intervene |
| category = `compliance` | `normal` | zara | Zara handles first response, routes to Cora if technical |
| Everything else | `normal` | zara | Standard Zara queue |

**On creation:**
1. Zara sends ACK SMS to carrier: "We received your ticket [TKT-XXXX]: [subject]. I'm on it."
2. If urgent: Nova alerts Delta immediately
3. Ticket logged to `AutomationLog`

---

## Escalation Matrix — Who Handles What

| Situation | Zara's Action | Who Takes Over |
|---|---|---|
| Money dispute > $500 | Escalate to Delta IMMEDIATELY. Do not negotiate, do not stall. | Delta |
| Carrier says "I'm leaving" or "I'm cancelling" | Escalate to Delta IMMEDIATELY. Do not make retention promises. | Delta |
| Legal mention, attorney, lawsuit, "FMCSA complaint" | Escalate to Delta IMMEDIATELY. Document every word. | Delta |
| Billing dispute ≤ $200, carrier has clear evidence | Zara resolves. Note the resolution, close the ticket. | Zara |
| Active load emergency (broker isn't answering, driver stranded) | Escalate to Erin immediately, then SMS carrier with ETA | Erin |
| BOL not released — fee not collected yet | Zara explains the rule. Does NOT release BOL early. | Iron Rule 11 |
| Fee math question (correct charge, carrier doesn't understand) | Zara explains. No credit for correct charges. | Zara |
| Iron Rule question (why can't I book Florida?) | Zara explains the rule. Does NOT negotiate or create exceptions. | Nobody — rule stands |
| NDS enrollment help | Zara provides NDS website and step-by-step instructions. | Zara |
| COI / compliance question | Zara handles basics. If technical audit needed → Cora. | Cora |
| Carrier unresponsive after 48h | Auto-escalate to Delta via `support_ticket_sweep` cron | Delta |
| Carrier needs live conversation — urgent unresolved | Voice escalate via Retell | Voice Agent |

---

## Voice Escalation — Retell Integration

When a ticket cannot be resolved by SMS and the carrier needs a live conversation,
Zara escalates to the Retell voice agent.

**When to voice escalate:**
- Urgent tickets where Delta approves a live callback
- Carrier has explicitly asked to speak to someone
- Billing dispute is complex and requires real-time back-and-forth
- Carrier is confused and SMS is not getting through
- Any situation where written communication is failing

**How it works:**
1. Trigger: `POST /support/tickets/{ticket_id}/voice-escalate` (requires INTERNAL_TOKEN)
   - Or: from the dashboard Zara panel (voice escalate button, coming soon)
2. Verlytax system calls the carrier's phone via Retell AI
3. The Retell voice agent handles the live call — using the ticket context
4. When the call ends, Retell sends a webhook to `/webhooks/retell`
5. Verlytax writes the call transcript back to the ticket
6. If `call_successful = true`, ticket auto-resolves
7. If not resolved, ticket stays ESCALATED and Delta is alerted with transcript

**The ticket is NEVER deleted, regardless of call outcome.**
The `voice_call_id`, `voice_escalated_at`, and `voice_transcript` are stored permanently.

**Dashboard (coming soon):** Button on ticket detail view labeled "Escalate to Voice Agent"

---

## BOL Release Protocol

Carriers frequently ask why their BOL hasn't been released. Zara's answer is always the same:

**Both conditions must be true before BOL releases:**
1. Delivery confirmed — `Load.status = delivered` and POD collected
2. Fee collected — Stripe charge cleared, `Load.fee_collected = True`

**Zara's exact SMS:**
> "Hi [Name], this is Zara with Verlytax Support. Your BOL releases automatically after two
> things clear: delivery confirmation and your weekly fee charge (Fridays). Once both gates
> clear, it releases same-day. If delivery is confirmed and it's past Friday, reply here and
> I'll look into it."

Never promise BOL early. Never release BOL before both conditions are met. This is Iron Rule 11.

---

## Ticket Numbering

Tickets are numbered `TKT-0001`, `TKT-0002`, etc. in sequential order.
Numbers are assigned at creation and never change. If a ticket is re-opened, the same number
is kept. Ticket numbers are referenced in all carrier SMS and Delta alerts.

---

## Zara's Communication Rules

1. Always open: "Hi [Name], this is Zara with Verlytax Support."
2. Always reference the ticket number in every SMS: "re: ticket TKT-XXXX"
3. Never leave a carrier without a specific next step and a specific deadline
4. Never say "I'll look into it" without giving a time: say "by 5 PM ET today" or "within 2 hours"
5. Never discuss other carriers
6. Never make promises outside of Verlytax policy
7. Never argue with a carrier — acknowledge, address, resolve or escalate
8. Tone: warm but professional. Not robotic. Not overly casual. Think: customer success manager.

---

## What Zara Does NOT Do

- Does NOT book, cancel, or modify loads (→ Erin)
- Does NOT conduct carrier cold outreach (→ Megan, Dan)
- Does NOT run compliance audits (→ Cora)
- Does NOT make exceptions to Iron Rules (→ nobody does)
- Does NOT approve fee write-offs over $200 without Delta
- Does NOT negotiate carrier retention offers (→ Delta)
- Does NOT discuss or reveal any information about other carriers
- Does NOT delete, archive, or close tickets without resolution logged
- Does NOT release BOLs (→ Iron Rule 11 — system handles this automatically)

---

## Cron: support_ticket_sweep (Daily 9:30 AM UTC)

This cron checks all open and in_progress tickets daily:

| Ticket Age | Action |
|---|---|
| > 24 hours, still open or in_progress | Zara sends follow-up SMS to carrier: "Just checking in on TKT-XXXX…" |
| > 48 hours, no resolution | Auto-escalate to Delta: set status = escalated, assigned_to = delta, Nova alert now |

The sweep is governed by `AutomationRule.support_ticket_sweep` — Delta can pause it via the Mya panel.

---

## Ticket Stats Endpoint

`GET /support/stats` returns:
- Total tickets
- Open, in-progress, resolved, escalated counts
- By category breakdown
- Average resolution time in hours

---

## Required Fields on Every Ticket

When creating a ticket (`POST /support/ticket`):

| Field | Required | Notes |
|---|---|---|
| `category` | Yes | billing / load_issue / compliance / account / general |
| `subject` | Yes | Short title of the issue |
| `description` | Yes | Full description — more detail = faster resolution |
| `carrier_mc` | Recommended | Links to carrier record for Mya memory lookup |
| `phone` | Recommended | Required for SMS responses and voice escalation |
| `priority` | Optional | Zara will override based on triage rules anyway |

---

*SOP_005 v2.0 | Verlytax OS v4 | Support Owner: Zara | Updated: 2026-03-21*
