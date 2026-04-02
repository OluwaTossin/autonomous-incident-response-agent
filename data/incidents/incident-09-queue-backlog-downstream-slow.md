# INC-009 — SQS backlog: workers blocked on slow Postgres reports query

| Field | Value |
|-------|--------|
| **Severity** | SEV-2 |
| **Environment** | production |
| **Window** | `2026-04-01T06:00Z` → `2026-04-01T09:30Z` |
| **Status** | resolved |

## Executive summary

Nightly **reporting** jobs enqueued messages faster than workers completed them. Each job ran a **long-running analytics query** on the primary OLTP DB (misconfigured after a schema change). Worker **concurrency** was fixed at 20; queries held connections and **CPU** on RDS, slowing every message.

## Impact

- **Oldest message age** peaked at **47 minutes** (SLA: 15 min for fraud-adjacent queue — **breached** for subset of messages moved to priority queue manually).
- OLTP p99 latency elevated for unrelated services sharing DB.

## Timeline (UTC)

| Time | Event |
|------|--------|
| 06:00 | `ApproximateAgeOfOldestMessage` alert |
| 06:20 | Workers healthy but **low throughput**; DB `active` queries high |
| 07:10 | Killed runaway queries; **paused** non-critical enqueue |
| 08:00 | Routed reporting reads to **replica**; added query timeout |
| 09:30 | Lag drained |

## Detection

CloudWatch SQS metrics + RDS performance insights.

## Root cause

**Architecture drift:** reporting job used writer; missing **replica** hint after table growth; no **statement_timeout** in app session.

## Resolution

Read-only replica for job; statement timeout; separate **small pool** for batch role; autoscale workers on **lag**.

## Runbooks

- **Primary:** `RB-QUEUE-LAG-009` — `docs/runbooks/runbook-09-queue-backlog-worker-lag.md`
- **Related:** `RB-DB-CONN-004`, `RB-GEN-HIGH-CPU-001`

```json
{
  "incident_id": "INC-009",
  "severity": "HIGH",
  "primary_runbook_ids": ["RB-QUEUE-LAG-009"],
  "related_runbook_ids": ["RB-DB-CONN-004", "RB-GEN-HIGH-CPU-001"],
  "services_affected": ["reports-worker", "rds-primary"],
  "symptoms": ["queue_backlog", "consumer_slow", "db_contention"],
  "root_cause_category": "architecture",
  "expected_triage_severity": "HIGH",
  "expected_escalate": true
}
```
