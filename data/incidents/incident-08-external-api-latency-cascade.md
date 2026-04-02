# INC-008 — Partner KYC API slow: retry storm inflated internal load

| Field | Value |
|-------|--------|
| **Severity** | SEV-2 |
| **Environment** | production |
| **Window** | `2026-03-22T15:10Z` → `2026-03-22T16:40Z` |
| **Status** | resolved |

## Executive summary

A third-party **KYC** provider degraded (elevated **p95** latency). Our service retried aggressively **without jitter**, doubling call volume and **CPU**. Internal thread pools saturated; **cascading timeouts** on unrelated endpoints sharing the same instance pool.

## Impact

- **~25%** of onboarding flows **timed out** during the window.
- Partner confirmed **regional** incident on their status page.

## Timeline (UTC)

| Time | Event |
|------|--------|
| 15:10 | Spike in `http_client_duration` to vendor host |
| 15:22 | Identified **retry multiplier** in logs |
| 15:35 | Deployed **circuit breaker** open + reduced max concurrency (feature flag) |
| 16:40 | Vendor recovered; gradual close of breaker |

## Detection

SLO burn on onboarding + vendor latency dashboard.

## Root cause

**Resilience gap:** no exponential backoff or bulkhead; retries amplified load during vendor brownout.

## Resolution

Tuned retry policy; added **bulkhead** per dependency; degraded mode returns **queued** state to UX.

## Runbooks

- **Primary:** `RB-EXT-API-008` — `docs/runbooks/runbook-08-external-api-dependency-failure.md`
- **Related:** `RB-GEN-HIGH-CPU-001`, `RB-HTTP-5XX-003`

```json
{
  "incident_id": "INC-008",
  "severity": "HIGH",
  "primary_runbook_ids": ["RB-EXT-API-008"],
  "related_runbook_ids": ["RB-GEN-HIGH-CPU-001", "RB-HTTP-5XX-003"],
  "services_affected": ["onboarding-api"],
  "symptoms": ["vendor_timeout", "retry_storm", "cascade_failure"],
  "root_cause_category": "dependency",
  "expected_triage_severity": "HIGH",
  "expected_escalate": true
}
```
