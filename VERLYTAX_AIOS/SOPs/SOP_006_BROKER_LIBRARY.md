# SOP_006 — Broker Library Management
**Version:** 1.0 | **Owner:** Delta | **Enforced by:** Erin + Mya

---

## Purpose

The Broker Library is Verlytax's internal knowledge base of brokers we work WITH.
It is NOT the blocked broker list (Iron Rule 8 / BlockedBroker table).
It tracks payment speed, lane coverage, reliability, and dispute history so Erin and Mya
can make smarter load-booking decisions and Delta always knows who to prioritize.

---

## When to Add a Broker

- Any time a new broker contacts Verlytax or we book our first load with them
- When Erin books a load from a broker not yet in the library → add them same day
- Add via `POST /brokers/add` with MC number, name, and any known lane/payment data

---

## Reliability Rating Scale (1–5)

| Rating | Meaning |
|---|---|
| 5 | Elite — pays fast, no disputes, high-value loads, preferred |
| 4 | Strong — reliable, occasional minor issues |
| 3 | Average — standard broker, no strong signals either way |
| 2 | Caution — slow pay or dispute history, use carefully |
| 1 | Poor — chronic issues; consider blocking via Iron Rule 8 |

**Delta sets reliability ratings manually. Mya updates load counts and payment days automatically.**

---

## How Mya Keeps It Updated

Every day at 6:00 AM UTC, Mya's `mya_learn()` cron:
1. Scans loads from the past 24 hours
2. Matches each load to a BrokerProfile by broker name
3. Increments `total_loads_booked` for each matched broker
4. Increments `total_disputes` if the load is in DISPUTED status
5. Recalculates `avg_payment_days` using rolling average of delivery→payment timing
6. Logs the sync in `automation_logs` as `broker_library_update`

---

## Marking Preferred Brokers

Set `is_preferred = true` on brokers with:
- Reliability rating 4 or 5
- avg_payment_days < 30
- Zero or low disputes

Preferred brokers appear first in `GET /brokers/list?is_preferred=true`
Erin should prioritize booking loads with preferred brokers.

---

## API Reference

| Endpoint | Action |
|---|---|
| `POST /brokers/add` | Add a new broker |
| `GET /brokers/list` | Search/filter broker list |
| `GET /brokers/{mc_number}` | Full broker profile |
| `PUT /brokers/{mc_number}/update` | Update any field |
| `GET /brokers/export/csv` | Download full library as CSV |

---

## What NOT to Do

- Never delete a broker from the library — update their rating instead
- Never add a broker who is already in the BlockedBroker table (Iron Rule 8)
- Never override Mya's payment day calculations manually unless data is clearly wrong

---

*SOP_006 v1.0 | Verlytax OS v4 | Created 2026-03-21*
