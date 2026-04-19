# INC-013 — RDS free storage low: writes stalled until resize

| Field | Value |
|-------|--------|
| **Severity** | SEV-1 |
| **Environment** | production |
| **Window** | `2026-02-02T03:40Z` → `2026-02-02T05:10Z` |
| **Status** | resolved |

## Executive summary

Automated **vacuum** lag and **index bloat** on a busy table consumed free space faster than forecast. RDS hit **FreeStorageSpace** critical threshold; engine entered **restricted write** behaviour; applications saw **timeouts** and **5xx**.

## Impact

- **All** services on shared writer: widespread errors for **~90 minutes** during resize and cleanup.
- **No** confirmed data corruption; brief **read-only** mode per engine behaviour.

## Timeline (UTC)

| Time | Event |
|------|--------|
| 03:40 | `FreeStorageSpace` critical + write latency |
| 03:55 | DBA initiated **storage autoscaling** + manual increase |
| 04:30 | Emergency **bloat** cleanup on replica promote plan (aborted — used online rebuild window) |
| 05:10 | Writes stable; space headroom restored |

## Detection

RDS CloudWatch + application DB error spike.

## Root cause

**Capacity planning** gap; autovacuum **not** keeping pace; **no** early warning at 25% free.

## Resolution

Increase allocated storage; tune autovacuum; add **predictive** alert on **free space trend**.

## Runbooks

- **Primary:** `RB-DISK-SAT-006` — `data/runbooks/runbook-06-disk-storage-saturation.md`
- **Related:** `RB-DB-CONN-004`, `RB-HTTP-5XX-003`

```json
{
  "incident_id": "INC-013",
  "severity": "CRITICAL",
  "primary_runbook_ids": ["RB-DISK-SAT-006"],
  "related_runbook_ids": ["RB-DB-CONN-004", "RB-HTTP-5XX-003"],
  "services_affected": ["rds-primary", "all-db-consumers"],
  "symptoms": ["disk_full", "db_write_failure", "timeouts"],
  "root_cause_category": "capacity",
  "expected_triage_severity": "CRITICAL",
  "expected_escalate": true
}
```
