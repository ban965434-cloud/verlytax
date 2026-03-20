# VERLYTAX SOP INDEX
## Standard Operating Procedures | Verlytax OS v4
### CEO: Delta | Last Updated: 2026-03-20

> Every SOP lives in this folder. When a process is learned, it gets written here.
> Transcripts, screenshots, and training media go to Google Drive → Training + Media/

---

## SOP Library

| # | File | Process | Status |
|---|---|---|---|
| 001 | `SOP_001_CARRIER_ONBOARDING.md` | 10-step carrier onboarding flow | ACTIVE |
| 002 | `SOP_002_LOAD_BOOKING.md` | Load booking + Iron Rules enforcement | ACTIVE |
| 003 | `SOP_003_DISPUTE_RESOLUTION.md` | Escalation, disputes, broker blocks | ACTIVE |

---

## How to Add a New SOP

**Option A — Via API (preferred):**
```
POST /brain/sops
{
  "filename": "SOP_004_MY_PROCESS.md",
  "content": "# SOP Title\n..."
}
```

**Option B — Direct file:**
Create `VERLYTAX_AIOS/SOPs/SOP_00X_TITLE.md` and add a row to this index.

**Naming convention:** `SOP_{number}_{TITLE_IN_CAPS}.md`

---

## SOP Format Template

```markdown
# SOP {number}: {Title}
## Last Updated: {date} | Owner: {agent or Delta}

### Purpose
What this SOP governs.

### Trigger
What event starts this process.

### Steps
1. Step one
2. Step two

### Guard Rails
- What must never happen
- Iron Rules involved

### Escalation
When to escalate to Delta.
```

---

*Verlytax SOPs v1 | CEO: Delta | 2026-03-20*
