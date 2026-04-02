# INC-001 — High CPU on `orders-api` after canary promotion

| Field | Value |
|-------|--------|
| **Severity** | SEV-2 (HIGH) |
| **Environment** | production |
| **Window** | `2026-03-18T09:14Z` → `2026-03-18T09:47Z` (mitigated) |
| **Status** | resolved |

## Executive summary

A canary release for `orders-api` increased per-request CPU by routing a new code path through an unindexed analytics join. Autoscaling added replicas but **per-pod CPU** stayed saturated; p99 latency rose until rollback.

## Impact

- Elevated **5xx** on checkout-adjacent reads (~3.2% at peak vs under 0.1% baseline).
- No data loss; **partial** customer-facing slowness for ~33 minutes.

## Timeline (UTC)

| Time | Event |
|------|--------|
| 09:14 | `CPUUtilizationHigh` + latency SLO burn |
| 09:18 | Confirmed correlation with **100% canary** promotion 12 min prior |
| 09:22 | Profiler sample: hot path in new handler |
| 09:35 | **Rollback** to previous deployment |
| 09:47 | Latency and CPU normalised |

## Detection

Grafana dashboard + PagerDuty composite alert (CPU + p99).

## Root cause

New release enabled **order enrichment** without DB index supporting the join; CPU spent in query execution and JSON serialisation under load.

## Resolution

Rollback deployment; emergency index created in maintenance window next day; re-release behind feature flag with load test gate.

## Runbooks

- **Primary:** `RB-GEN-HIGH-CPU-001` — `docs/runbooks/runbook-01-high-cpu-usage.md`
- **Related:** `RB-PAYMENT-API-HIGH-CPU-001` (if payment-adjacent), `RB-HTTP-5XX-003`

## Follow-ups

- [ ] Block canary promotion on **CPU regression** budget vs baseline.
- [ ] Add **query plan** check in CI for flagged migrations.

```json
{
  "incident_id": "INC-001",
  "severity": "HIGH",
  "primary_runbook_ids": ["RB-GEN-HIGH-CPU-001"],
  "related_runbook_ids": ["RB-HTTP-5XX-003", "RB-PAYMENT-API-HIGH-CPU-001"],
  "services_affected": ["orders-api"],
  "symptoms": ["high_cpu", "latency", "post_deploy"],
  "root_cause_category": "release_regression",
  "expected_triage_severity": "HIGH",
  "expected_escalate": true
}
```
