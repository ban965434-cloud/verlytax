# VERLYTAX DECISION ENGINE
## 5-Stage Autonomous Decision Thresholds
### Verlytax OS v4 | CEO: Delta | 2026-03-20

> This file defines exactly what each agent can decide alone, what requires a log,
> what requires Delta's confirmation, and what is a hard block with zero exceptions.
> Every agent reads this before acting. When in doubt, go up a stage — never down.

---

## The 5 Stages

```
STAGE 1 — AUTO-HANDLE       Agent acts alone. No alert. No log required.
STAGE 2 — HANDLE + LOG      Agent acts. Logs to DB. No Nova alert.
STAGE 3 — HANDLE + ALERT    Agent acts. Logs to DB. Nova alerts Delta.
STAGE 4 — PAUSE + ESCALATE  Agent STOPS. Does nothing. Nova alerts Delta. Waits.
STAGE 5 — HARD BLOCK        Iron Rule violation. Auto-reject. Log. Alert Delta.
```

---

## Stage 1 — AUTO-HANDLE
**Agent acts alone. No approval needed. No alert.**

These are routine, fully within Erin's mandate, no money risk, reversible.

| Action | Who | Condition |
|---|---|---|
| Iron Rule auto-rejection | Erin | Any Iron Rule violation on a load |
| Load booking | Erin | RPM ≥ $2.75, deadhead ≤ 25%, all Iron Rules pass |
| Standard carrier onboarding steps | Erin/Brain | Compliance passed, all docs in DB |
| Send Day 1 carrier packet | Nova | Trial just activated |
| Day 3 trial check-in SMS | Nova | Cron fires, sms_day3_sent = False |
| Day 7 convert offer SMS | Nova | Cron fires, sms_day7_sent = False |
| Day 14 win-back SMS | Nova | Cron fires, sms_day14_sent = False |
| Day 30 win-back SMS | Nova | Cron fires, sms_day30_sent = False |
| Invoice generation | Erin | POD collected, load = delivered |
| Billing dispute under $200 with clear evidence | Erin | Evidence in DB, < $200 |
| FMCSA lookup | Brain | Any compliance check |
| Inbound SMS response | Erin | Standard carrier question |
| Lead outreach response | Erin | Standard qualification |
| Counter-offer at $2.51–$2.74 RPM | Erin | Push up to $2.75+ before accepting |
| Confirm delivery + collect POD | Erin | Driver confirms delivery |
| BOL release after delivery confirmed | Erin | pod_collected = True |

---

## Stage 2 — HANDLE + LOG
**Agent acts. Logs outcome to escalation_logs. No alert to Delta.**

These are actions with a track record and defined rules, but worth logging for Delta's review.

| Action | Who | Condition | What Gets Logged |
|---|---|---|---|
| Counter-offer accepted below $2.75 (at $2.51–$2.74 range) | Erin | Iron Rule 2 passed, counter sent and accepted | Load ID, RPM, counter details |
| Carrier goes trial → inactive (no convert at Day 7) | Brain/Erin | Trial expired, carrier did not respond | Carrier MC, dates, reason |
| Carrier marked inactive at Day 30 | Brain | 30-day win-back fired, no response | Carrier MC, final status |
| Standard fee collection (Friday run) | Brain | All charges succeed | Each carrier, amount charged |
| Broker block (standard bad faith — confirmed pattern) | Erin | 2+ disputes with clear evidence, under $500 total | Broker name, MC, reason, dat_filed |
| Load booked on counter-offer lane | Erin | RPM $2.51–$2.74 accepted after counter | Load ID, RPM, counter delta |

---

## Stage 3 — HANDLE + ALERT
**Agent acts AND sends Nova alert to Delta. Delta is informed but not required to act.**

These are significant events. Delta needs to know but Erin has the mandate to handle them.

| Action | Who | Condition | Nova Message |
|---|---|---|---|
| Single carrier fee charge fails | Brain/Stripe | Payment declined | "PAYMENT FAILED — [name] MC#[X]. Carrier suspended. $[amount]." |
| Carrier suspended for non-payment | Brain | Stripe failure on Friday run | "Carrier [name] suspended — payment failed. Review needed." |
| Dispute opened under $200 | Erin | Carrier or broker files dispute | "[name] filed dispute. $[amount]. Erin handling. 48-hour window." |
| Friday fee run complete | Brain | Cron completes | Full summary: charged / failed / skipped |
| Trial expired — no convert | Brain | Day 7 passed, no YES response | "[name] MC#[X] trial ended — no convert. Win-back sequence active." |
| System startup | App | Railway deploy | "Verlytax OS v4 live. Erin, Nova, Brain online." |
| New carrier enters trial | Erin | Trial activation | "[name] MC#[X] trial activated. Day 1 packet sent." |
| New carrier converts to active | Erin | Trial → active, Stripe attached | "[name] MC#[X] active. Stripe attached. First Friday charge scheduled." |

---

## Stage 4 — PAUSE + ESCALATE
**Agent stops all action. Nova alerts Delta immediately. Agent waits for Delta's decision.**

These require Delta's judgment. No agent proceeds without Delta's explicit YES.

| Trigger | Who Pauses | Nova Message | Agent Waits For |
|---|---|---|---|
| Any money decision over $500 | Erin | "ESCALATION — $[amount] decision needed. [details]. Awaiting your call." | Delta: approve / deny / negotiate |
| Carrier threatening to leave | Erin | "RETENTION ALERT — [name] MC#[X] threatening to leave. Stand by." | Delta: keep / hold / drop |
| Dispute unresolved after 48 hours | Erin | "DISPUTE UNRESOLVED 48HR — [name]. $[amount]. Need your decision." | Delta: dispute / negotiate / write-off |
| Billing dispute over $200 | Erin | "BILLING DISPUTE $[amount] — [name]. Evidence [clear/unclear]." | Delta: handle direction |
| New region or market decision | Any | "EXPANSION DECISION required — [details]." | Delta only |
| Legal document needing signature | Any | "LEGAL SIGNATURE NEEDED — [document type]. Do not proceed." | Delta signs |
| Ad spend increase request | Any | "AD SPEND REQUEST — $[amount]. Current: $[current]. Awaiting approval." | Delta: approve / deny |
| Bad faith broker block confirmation (over $500) | Erin | "BAD FAITH BLOCK — [broker name]. $[amount] disputed. Confirm block?" | Delta: confirm / negotiate |
| Bank transfer requiring 2FA | Any | "2FA TRANSFER — $[amount] to [destination]. Standing by." | Delta completes 2FA |
| Anything never seen before | Any | "UNKNOWN SITUATION — [description]. No protocol exists. Need your call." | Delta decides |
| Factoring dispute (any amount) | Erin | "FACTORING DISPUTE — [carrier] / [factor]. $[amount]. Immediate attention." | Delta escalates |

---

## Stage 5 — HARD BLOCK
**Iron Rule violation. Auto-reject. Log to DB. Nova alert to Delta. No negotiation.**

These are non-negotiable. No agent, no carrier, no rate, no situation overrides them.

| Iron Rule Violated | What Fires |
|---|---|
| Rule 1 — Florida load (pickup or delivery) | Reject load. Log. Nova: "Iron Rule 1 violation — FL load blocked. [details]." |
| Rule 2 — RPM below $2.51 | Reject load. Log. Nova: "Iron Rule 2 — RPM $[X] below floor. Load rejected." |
| Rule 3 — Deadhead over 50mi or 25% | Reject load. Log. Nova: "Iron Rule 3 — Deadhead $[X]mi / [Y]%. Load rejected." |
| Rule 4 — Weight over 48,000 lbs | Reject load. Log. Nova: "Iron Rule 4 — Weight [X]lbs. Load rejected." |
| Rule 5 — Unsatisfactory/Conditional rating | Block carrier. Log. Nova: "Iron Rule 5 — [carrier] safety rating: [X]. Blocked." |
| Rule 6/10 — Authority under 180 days | Block carrier. Log. Nova: "Iron Rule 6 — [carrier] authority [X] days old. Blocked." |
| Rule 7 — Failed Clearinghouse | Block carrier. Log immediately. Nova: "Iron Rule 7 — Clearinghouse FAILED. [carrier] MC#[X]. Logged." |
| Rule 8 — Blocked broker | Reject load. Log. Nova: "Iron Rule 8 — [broker] is in memory_brokers. Load rejected." |
| Rule 9 — NDS not enrolled | Block dispatch. Log. Nova: "Iron Rule 9 — [carrier] NDS not enrolled. Cannot dispatch." |
| Rule 11 — BOL before delivery | Block release. Log. Nova: "Iron Rule 11 — BOL release blocked. Delivery not confirmed." |

**Hard Block rules:**
- The violation is always logged in `escalation_logs` with `issue_type = "iron_rule_violation"`
- Delta always receives the Nova alert — even if it's 2 AM
- No agent can un-block a Stage 5 without Delta's explicit instruction
- Claude Code cannot modify Iron Rules under any circumstance

---

## Decision Tree for Edge Cases

When a situation doesn't fit a clean stage:

```
1. Does it involve an Iron Rule?
   YES → Stage 5. Full stop.

2. Does it involve money over $500?
   YES → Stage 4. Stop and alert Delta.

3. Does it involve a carrier threatening to leave?
   YES → Stage 4. Stop and alert Delta.

4. Has this situation come up before with a clear resolution in escalation_logs?
   YES → Follow that precedent. Stage 2 (log).

5. Is it a routine, reversible action within defined rules?
   YES → Stage 1 or 2.

6. None of the above?
   → Stage 4. Alert Delta. "Unknown situation — no protocol exists."
```

---

## Escalation Resolution Tracker

After Delta resolves a Stage 4 escalation, the resolution is logged and becomes precedent.

| Resolution Type | What It Means | Future Behavior |
|---|---|---|
| DISPUTE | File with DAT + broker flagged | 2+ disputes → automatic Stage 5 block |
| NEGOTIATE | Counter at 83% minimum | Erin handles follow-up |
| WRITE OFF | Threshold $500 or less | Log, mark resolved, no further action |
| KEEP | Carrier retention — Delta's call | Erin continues normal ops |
| HOLD | Wait for more data | 24-hour re-escalation |
| DROP | Carrier off-boarded | Carrier status → inactive or blocked |

---

*Verlytax Decision Engine v1 | CEO: Delta | 2026-03-20*
