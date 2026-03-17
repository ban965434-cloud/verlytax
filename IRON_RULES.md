# IRON RULES — VERLYTAX OS v4
### Non-Negotiable. No Exceptions. No Bypasses. Ever.
Last Updated: March 14, 2026 | CEO: Delta

---

> These rules are absolute. No carrier, broker, rate, or situation overrides them.
> Any agent — Erin, Nova, Brain, or CEO Agent — that bypasses an Iron Rule is in violation.
> Delta holds the only override key.

---

## THE 11 IRON RULES

| # | Rule | Action |
|---|---|---|
| 1 | **NO FLORIDA LOADS** | Reject immediately. No exceptions. Ever. |
| 2 | **MIN RPM $2.51** | Hard floor. Never counter below this. Instant reject. |
| 3 | **MAX DEADHEAD 50 miles / 25%** | Do not book if either limit is exceeded. |
| 4 | **MAX WEIGHT 48,000 lbs** | Hard limit. No exceptions. |
| 5 | **NO UNSATISFACTORY / CONDITIONAL safety ratings** | Instant reject. |
| 6 | **AUTHORITY AGE 180+ DAYS** | Hard reject under 180 days. No exceptions. |
| 7 | **FAILED FMCSA CLEARINGHOUSE** | Instant reject. Log block immediately. |
| 8 | **BLOCKED BROKER in memory_brokers** | Never rebook. Ever. |
| 9 | **NDS ENROLLMENT BEFORE DAY 1 LOAD** | Carrier completes before first dispatch. |
| 10 | **AUTHORITY AGE VERIFIED** | 180-day minimum confirmed before onboarding. |
| 11 | **NEVER RELEASE BOL BEFORE DELIVERY CONFIRMED** | No exceptions. Ever. |

---

## RULE DETAILS

### Rule 1 — NO FLORIDA LOADS
Florida loads are permanently excluded from Verlytax operations.
This rule applies to pickups AND deliveries in Florida.
No rate, no carrier, no situation changes this.

### Rule 2 — MIN RPM $2.51
$2.51 is the absolute minimum rate per mile accepted.
- Below $2.51 → HARD REJECT. Do not counter. Do not negotiate.
- $2.51–$2.74 → Counter-offer required before accepting.
- $2.75–$2.99 → Acceptable. Book.
- $3.00+ → Excellent. Prioritize.

### Rule 3 — MAX DEADHEAD 50 miles / 25%
Dead miles cost the carrier money and reduce profitability.
- Over 50 miles empty OR over 25% deadhead ratio → Do not book.
- Both limits apply. Exceeding either triggers rejection.

### Rule 4 — MAX WEIGHT 48,000 lbs
Hard weight limit for all loads.
No exceptions for any carrier, broker, or rate level.

### Rule 5 — NO UNSATISFACTORY / CONDITIONAL SAFETY RATINGS
Check FMCSA portal before every new carrier relationship.
- Unsatisfactory rating → Instant reject.
- Conditional rating → Instant reject.
- No rating on file → Verify before proceeding.

### Rule 6 — AUTHORITY AGE 180+ DAYS
New carriers (under 180 days of active authority) are not dispatched.
Verify at: [safer.fmcsa.dot.gov](https://safer.fmcsa.dot.gov)
Authority age is confirmed during compliance check — not assumed.

### Rule 7 — FAILED FMCSA CLEARINGHOUSE
Every carrier must pass the FMCSA Drug & Alcohol Clearinghouse query.
- Cost: $1.25 per query
- Fail → Instant reject. Log block in verlytax.db immediately.
- Annual re-query required on all active carriers.

### Rule 8 — BLOCKED BROKER IN memory_brokers
Any broker flagged for bad faith is permanently blocked.
Blocked brokers never appear in load searches again.
No re-booking. No second chances. No exceptions.

### Rule 9 — NDS ENROLLMENT BEFORE DAY 1 LOAD
Carrier must complete NDS enrollment before their first dispatched load.
- Cost: $100/year (carrier pays)
- No enrollment = No dispatch. Zero exceptions.

### Rule 10 — AUTHORITY AGE VERIFIED
Authority age must be confirmed with a live FMCSA portal check.
Paper certificates are not sufficient. Online verification required.
180 days minimum — confirmed before onboarding proceeds.

### Rule 11 — NEVER RELEASE BOL BEFORE DELIVERY CONFIRMED
The Bill of Lading is never released until delivery is confirmed.
This protects the carrier and Verlytax from fraud and disputes.
No exceptions for any broker, any load, any situation.

---

## ENFORCEMENT

These rules are enforced by:
- **Erin** — auto-rejects at load booking stage
- **Brain** — compliance check at onboarding
- **Iron Rules Enforcer** — system-level guard layer

Violations are logged in verlytax.db and escalated to Delta immediately.

---

## WHAT IRON RULES ARE NOT

Iron Rules are **not** negotiable under any of the following:
- High-value loads
- Carrier request or pressure
- Broker relationships
- Emergency situations
- Delta being unavailable

**The only person who can modify an Iron Rule is Delta.**

---

*Verlytax OS v4 | Iron Rules v1.0 | CEO: Delta | March 14, 2026*
