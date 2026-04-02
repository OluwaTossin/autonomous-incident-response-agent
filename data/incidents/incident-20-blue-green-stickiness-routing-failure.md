# INC-020 — Blue/green: stickiness pinned users to unstable green fleet

| Field | Value |
|-------|--------|
| **Severity** | SEV-1 (CRITICAL) |
| **Environment** | production |
| **Window** | `2026-05-27T20:03Z` → `2026-05-27T20:55Z` (core impact) |
| **Status** | resolved |

## Executive summary

During **ECS blue/green** with ALB, **listener weights** and **target group stickiness** interacted so that **more traffic than intended** reached **green**. Green passed **shallow** health checks but a **downstream dependency** was not warm. **Returning sessions** stayed on green via stickiness, so impact **persisted** after partial rollback until weights and sessions cleared.

## Impact

- **~13%** of active users affected disproportionately (**session-based**); green **error rate ~21%** vs blue **~1%**.
- **~52 minutes** to full stabilisation (stickiness tail).

## Timeline (UTC)

| Time | Event |
|------|--------|
| 20:03 | Deployment start |
| 20:06 | Detection: split user reports + green error metrics |
| 20:12 | Compared **expected** vs **actual** target group weight |
| 20:25 | Forced **100% blue**; disabled unintended weighting |
| 20:55 | User errors subsided after stickiness expiry window |

## Detection

Error rate dashboards + customer reports; **confusing** because blue healthy.

## Root cause

**Deployment mechanics:** listener rule not in expected state; **stickiness** prolonged exposure; **health checks** insufficient for **dependency readiness**.

## Resolution

Drain green; full blue; fix listener IaC; expand readiness to include **dependency warm** path; dashboard for **expected vs actual** traffic split.

## Runbooks

- **Primary:** `RB-LB-HEALTH-010` — `data/runbooks/runbook-10-load-balancer-unhealthy-targets.md`
- **Related:** `RB-HTTP-5XX-003`, `RB-EXT-API-008`

## Structured record (JSON)

For eval harnesses and tooling, the same incident can be loaded as JSON:

```json
{
  "incident_id": "INC-020",
  "title": "Blue-green cutover exposed users to unstable green fleet due to target group weighting and stickiness interaction",
  "environment": "production",
  "services_affected": ["frontend-app", "api-gateway", "green-environment", "blue-environment"],
  "platform": "Amazon ECS blue/green with ALB",
  "timestamp_start": "2026-05-27T20:03:00Z",
  "timestamp_detected": "2026-05-27T20:06:00Z",
  "severity": "CRITICAL",
  "status": "resolved",
  "duration_minutes": 52,
  "summary": "During a planned blue-green deployment, green received more traffic than intended due to listener weighting and stickiness. Users pinned to green hit an unwarmed downstream path; rollback was delayed by session stickiness.",
  "primary_runbook_ids": ["RB-LB-HEALTH-010"],
  "related_runbook_ids": ["RB-HTTP-5XX-003", "RB-EXT-API-008"],
  "metrics": {
    "expected_green_weight_percent": 10,
    "effective_green_traffic_percent_peak": 34,
    "green_error_rate_percent": 21,
    "blue_error_rate_percent": 1,
    "sticky_session_affected_user_percent": 13
  },
  "root_cause_category": "deployment_mechanics",
  "expected_triage_severity": "CRITICAL",
  "expected_escalate": true,
  "confidence": 0.96
}
```
