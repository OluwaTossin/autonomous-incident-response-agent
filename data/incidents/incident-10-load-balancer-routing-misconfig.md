# INC-010 — Listener rule sent `/api/v2/*` to wrong target group

| Field | Value |
|-------|--------|
| **Severity** | SEV-2 |
| **Environment** | production |
| **Window** | `2026-02-28T13:05Z` → `2026-02-28T13:52Z` |
| **Status** | resolved |

## Executive summary

A manual ALB listener rule edit during **incident drill prep** accidentally matched **`/api/v2/*`** before the default rule, sending traffic to a **deprecated** internal test target group (stale ASG). **v2** clients received **502**; **v1** unaffected.

## Impact

- **~40%** of API traffic (v2 clients) failed for ~47 minutes.
- Drill was **not** approved for prod — **process violation**.

## Timeline (UTC)

| Time | Event |
|------|--------|
| 13:05 | 502 spike on v2 routes only |
| 13:12 | ALB access logs showed wrong target group ARN |
| 13:25 | Reverted rule priority and path pattern via IaC apply |
| 13:52 | Error rate normal |

## Detection

Route-specific error dashboard + synthetics on v2.

## Root cause

**Manual console change** bypassing Terraform; **no** peer review; rule priority inversion.

## Resolution

IaC revert; locked listener **write** to pipeline only; imported current state to avoid drift.

## Runbooks

- **Primary:** `RB-LB-HEALTH-010` — `data/runbooks/runbook-10-load-balancer-unhealthy-targets.md`
- **Related:** `RB-HTTP-5XX-003`

```json
{
  "incident_id": "INC-010",
  "severity": "HIGH",
  "primary_runbook_ids": ["RB-LB-HEALTH-010"],
  "related_runbook_ids": ["RB-HTTP-5XX-003"],
  "services_affected": ["public-api-v2"],
  "symptoms": ["502", "wrong_target_group", "partial_outage"],
  "root_cause_category": "misconfiguration",
  "expected_triage_severity": "HIGH",
  "expected_escalate": true
}
```
