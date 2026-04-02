# INC-012 — ALB 504: idle timeout shorter than long report request

| Field | Value |
|-------|--------|
| **Severity** | SEV-2 |
| **Environment** | production |
| **Window** | `2026-01-30T10:00Z` → `2026-01-30T11:35Z` |
| **Status** | resolved |

## Executive summary

Heavy **CSV export** requests ran **over 60 seconds** after a DB regression. ALB **idle timeout** was **60 s**; LB closed the connection while the app still processed → clients saw **504**. App logs showed **200** completed late (orphaned work).

## Impact

- **Exports** (roughly 8% of large jobs) failed for large accounts; interactive API fine.
- Wasted **compute** on abandoned requests.

## Timeline (UTC)

| Time | Event |
|------|--------|
| 10:00 | 504 spike correlated with `/export` route |
| 10:25 | ALB access log: `elb_status_code=504`, `target_status_code=-` |
| 10:40 | Raised idle timeout to **300 s** (temporary) |
| 11:00 | Shipped **async export** via job + presigned URL (proper fix) |
| 11:35 | Stable |

## Detection

Route-specific 5xx + customer support tickets.

## Root cause

**Synchronous** long work behind synchronous LB; **no** async pattern; DB query plan regression increased duration over LB limit.

## Resolution

Async job pattern; tuned query; ALB timeout aligned only as safety net.

## Runbooks

- **Primary:** `RB-HTTP-5XX-003` — `docs/runbooks/runbook-03-http-5xx-spike.md`
- **Related:** `RB-LB-HEALTH-010`, `RB-DB-CONN-004`

```json
{
  "incident_id": "INC-012",
  "severity": "HIGH",
  "primary_runbook_ids": ["RB-HTTP-5XX-003"],
  "related_runbook_ids": ["RB-LB-HEALTH-010", "RB-DB-CONN-004"],
  "services_affected": ["reports-api"],
  "symptoms": ["504", "alb_timeout", "long_request"],
  "root_cause_category": "architecture",
  "expected_triage_severity": "MEDIUM",
  "expected_escalate": false
}
```
