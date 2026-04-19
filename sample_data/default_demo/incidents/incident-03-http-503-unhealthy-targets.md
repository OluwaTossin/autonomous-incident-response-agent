# INC-003 — ALB 503s: all targets unhealthy after health path change

| Field | Value |
|-------|--------|
| **Severity** | SEV-1 |
| **Environment** | production |
| **Window** | `2026-01-22T16:03Z` → `2026-01-22T16:21Z` |
| **Status** | resolved |

## Executive summary

A deployment changed the app to expose **`/live`** for liveness but the ALB target group still probed **`/health`**, which now returned **404**. All targets marked **unhealthy**; ALB returned **503** to clients despite processes running.

## Impact

- **Full** regional API unavailability for **~18 minutes**.
- Zero successful writes; mobile clients showed generic error.

## Timeline (UTC)

| Time | Event |
|------|--------|
| 16:03 | Mass 503, `UnHealthyHostCount` = desired count |
| 16:06 | Direct pod curl: `/health` 404, `/live` 200 |
| 16:09 | Updated target group health check path (emergency change) |
| 16:21 | All targets healthy; error rate baseline |

## Detection

Synthetic check + customer social spike (backup signal).

## Root cause

**Drift** between application router and infrastructure-as-code: Helm chart updated paths; Terraform **not** applied in same release train.

## Resolution

Point health check to **`/live`**; add CI contract test **ALB path == app**; single MR for app + TF.

## Runbooks

- **Primary:** `RB-LB-HEALTH-010` — `data/runbooks/runbook-10-load-balancer-unhealthy-targets.md`
- **Related:** `RB-HTTP-5XX-003`

```json
{
  "incident_id": "INC-003",
  "severity": "CRITICAL",
  "primary_runbook_ids": ["RB-LB-HEALTH-010"],
  "related_runbook_ids": ["RB-HTTP-5XX-003"],
  "services_affected": ["public-api"],
  "symptoms": ["503", "unhealthy_targets", "deploy_correlated"],
  "root_cause_category": "misconfiguration",
  "expected_triage_severity": "CRITICAL",
  "expected_escalate": true
}
```
