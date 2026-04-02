# INC-004 — Postgres `too many connections` during Black Friday scale-out

| Field | Value |
|-------|--------|
| **Severity** | SEV-1 |
| **Environment** | production |
| **Window** | `2025-11-29T04:12Z` → `2025-11-29T04:55Z` |
| **Status** | resolved |

## Executive summary

Autoscaling increased `cart-api` replicas for traffic; each pod used **maxPoolSize=50**. Total app connections exceeded RDS **`max_connections`** minus reserved slots. New queries failed with **`FATAL: too many connections`**, cascading to **5xx**.

## Impact

- Checkout errors **~8%** for ~43 minutes; revenue impact contained by queue-hold UX.
- Writer connections near ceiling — **risk** to all consumers of shared cluster.

## Timeline (UTC)

| Time | Event |
|------|--------|
| 04:12 | DB connection alert + app pool wait timeouts |
| 04:18 | Counted replicas × pool max &gt; safe budget |
| 04:25 | **Scaled in** non-critical workers; reduced per-pod pool cap via config |
| 04:40 | DBA raised `max_connections` **temporarily** with CPU review |
| 04:55 | Stable with headroom |

## Detection

RDS `DatabaseConnections` + application `hikaricp.connections.pending`.

## Root cause

**Capacity formula** not enforced in CI: replica max × pool max exceeded planned DB ceiling; no RDS Proxy.

## Resolution

Emergency pool reduction + short `max_connections` bump; follow-up RDS Proxy + documented budget per service.

## Runbooks

- **Primary:** `RB-DB-CONN-004` — `docs/runbooks/runbook-04-database-connection-exhaustion.md`
- **Related:** `RB-HTTP-5XX-003`

```json
{
  "incident_id": "INC-004",
  "severity": "CRITICAL",
  "primary_runbook_ids": ["RB-DB-CONN-004"],
  "related_runbook_ids": ["RB-HTTP-5XX-003"],
  "services_affected": ["cart-api", "rds-primary"],
  "symptoms": ["too_many_connections", "pool_exhausted", "5xx"],
  "root_cause_category": "capacity",
  "expected_triage_severity": "CRITICAL",
  "expected_escalate": true
}
```
