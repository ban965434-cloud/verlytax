# VERLYTAX AUTOMATION SCHEDULE
## Every Automation — Time / Agent / Trigger / Action
### Verlytax OS v4 | CEO: Delta | 2026-03-20

> This is the complete map of every automated action in the Verlytax OS.
> Nothing should surprise you here. Every fire is documented.
> Status: LIVE = running in production. READY = built, not wired. NOT BUILT = roadmap.

---

## Recurring Cron Jobs (APScheduler)

### JOB 1 — Trial Touchpoints (Daily)
| Field | Value |
|---|---|
| **Schedule** | Daily at 8:00 AM ET (America/New_York) |
| **Agent** | Brain (scheduler) + Nova (SMS) |
| **Code** | `app/main.py → check_trial_touchpoints()` |
| **Status** | LIVE |

**What it does:**
Scans all carriers with `trial_start_date` set, status = `trial` or `inactive`, not blocked.
Fires the right SMS via Nova based on days elapsed:

| Day | SMS Fired | Condition |
|---|---|---|
| Day 3 | Mid-trial check-in: "How's everything going?" | `sms_day3_sent = False` and `status = trial` |
| Day 7 | Convert offer: "Trial ends today — reply YES to go active" | `sms_day7_sent = False` and `status = trial` |
| Day 14 | Win-back 1: "We still have your account ready" | `sms_day14_sent = False` and `status = trial` |
| Day 30 | Win-back 2 + mark inactive | `sms_day30_sent = False` (any status) |

After Day 30: carrier status → `inactive`, Delta gets Nova alert.

---

### JOB 2 — Friday Fee Charge (Weekly)
| Field | Value |
|---|---|
| **Schedule** | Every Friday at 9:00 AM ET (America/New_York) |
| **Agent** | Brain (scheduler) + Stripe (charge) + Nova (alert) |
| **Code** | `app/main.py → friday_fee_charge()` |
| **Status** | LIVE |

**What it does:**
1. Pulls all active carriers with a Stripe customer ID, not blocked.
2. Sums all unchartered loads (`fee_collected = False`, `status = delivered`).
3. Calculates fee on gross revenue via `calculate_fee()`.
4. Charges via Stripe `PaymentIntent`.
5. On success: marks loads `fee_collected = True`, `invoice_paid_at = now`.
6. On failure: carrier status → `suspended` immediately.
7. Sends full summary to Delta via Nova: charged / failed / skipped counts.

---

## Event-Triggered Automations

### ON: New Carrier Trial Activated
| Trigger | `POST /onboarding/activate-trial` succeeds |
| Agent | Nova |
| Action | Send Day 1 carrier packet SMS via `nova_day1_carrier_packet()` |
| Content | Welcome + packet link + MC# + ops@verlytax.com |
| Status | LIVE |

---

### ON: App Startup (Railway Deploy)
| Trigger | FastAPI lifespan starts |
| Agent | Nova |
| Action | `nova_alert_ceo("Verlytax OS v4 — System Live", ...)` |
| Content | "App started successfully on Railway. Erin, Nova, and Brain are online." |
| Status | LIVE |

---

### ON: Inbound Carrier SMS
| Trigger | `POST /webhooks/twilio/sms` fires |
| Agent | Erin |
| Action | Parse message body → `erin_respond()` → reply via Nova SMS |
| Auth | Twilio signature verified via `verify_twilio_signature()` |
| Status | LIVE |

---

### ON: Stripe Payment Event
| Trigger | `POST /webhooks/stripe` fires |
| Agent | Brain (handler) + Nova (alert if failure) |
| Action | Process `payment_intent.succeeded` or `payment_intent.payment_failed` |
| Auth | Stripe webhook signature verified |
| Status | LIVE |

---

### ON: Load Booking
| Trigger | `POST /billing/load/book` succeeds |
| Agent | Erin (Iron Rules check runs first) |
| Action | Save load to DB, calculate fee, return load_id and fee info |
| Iron Rules | All 11 checked before booking |
| Status | LIVE |

---

### ON: Carrier Fee Fails (any load-level charge)
| Trigger | `POST /billing/collect-fee/{load_id}` — Stripe returns failed |
| Agent | Nova + Erin |
| Action | SMS carrier to update payment method + Nova alert Delta + carrier → suspended |
| Status | LIVE |

---

### ON: Delivery Confirmed
| Trigger | `POST /billing/load/{load_id}/deliver` |
| Agent | Erin |
| Action | Load → `delivered`, `pod_collected = True`, `invoice_sent_at = now` |
| Next Step | Fee collection unlocked. BOL release unlocked. |
| Status | LIVE |

---

### ON: Dispute Opened
| Trigger | `POST /escalation/create` |
| Agent | Erin (logs) + Nova if > $200 or unresolved 48hr |
| Action | Stage 2 (< $200, clear evidence) or Stage 4 (> $200, unclear, > 48hr) |
| Status | LIVE |

---

### ON: Broker Block Confirmed
| Trigger | `POST /escalation/broker/block` |
| Agent | Erin/Brain |
| Action | Write to `memory_brokers` table permanently. Never delete. |
| Status | LIVE |

---

## Automations That Are READY (Built, Not Wired)

### Retell Voice Call Handler
| Trigger | `POST /webhooks/retell` |
| Agent | Retell AI → Erin |
| Status | READY — webhook skeleton exists, logic not wired |
| What's needed | Wire Retell callback to `erin_respond()` with call transcript |
| Roadmap | Priority 2 in CLAUDE.md |

---

## Automations NOT YET BUILT (Roadmap)

### /erin/chat Endpoint
| Priority | 1 (highest) |
| What | Connect dashboard chat box to `erin_respond()` live |
| Where | New route in `app/routes/` or `app/main.py` |
| Effort | Small — function exists, just need the endpoint + dashboard wiring |

---

### Annual FMCSA Re-Query (Brain)
| Priority | 3 |
| What | Re-check all active carriers' FMCSA Clearinghouse once per year |
| Why | Iron Rule 7 — prevent carrying unsafe operators long-term |
| Code needed | New APScheduler job: annually, scan all `status = active` carriers |

---

### Day 30 Testimonial Request
| Priority | 4 |
| What | Nova SMS at Day 30 and Day 60 asking for carrier testimonial |
| Code needed | Add to `check_trial_touchpoints()` or new cron |

---

### DocuSign Agreement at Day 5
| Priority | 5 |
| What | Auto-send service agreement PDF via DocuSign at Day 5 of trial |
| Code needed | DocuSign API integration + new touchpoint in trial cron |

---

### DAT Rate Feed
| Priority | 6 |
| What | Pull live RPM data per lane for scoring |
| Code needed | DAT API integration in `app/services.py` |

---

### Canada Phase 2 Compliance
| Priority | HOLD — do not build |
| What | NSC/CVOR/SAAQ compliance layer |
| Status | DO NOT BUILD until Delta explicitly activates |

---

## Automation Health Check

Run this mentally at the start of every session:

| Check | Expected State |
|---|---|
| APScheduler started | Yes — `lifespan()` in `main.py` |
| Friday cron firing | Yes — `day_of_week=fri, hour=9, timezone=America/New_York` |
| Daily touchpoints firing | Yes — `hour=8, timezone=America/New_York` |
| Twilio webhook active | Yes — `/webhooks/twilio/sms` |
| Stripe webhook active | Yes — `/webhooks/stripe` |
| CEO Nova alert on startup | Yes — fires every deploy |
| Iron Rules enforcer active | Yes — every load booking runs `check_load()` |

---

*Verlytax Automation Schedule v1 | CEO: Delta | 2026-03-20*
