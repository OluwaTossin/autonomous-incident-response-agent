# INC-016 — RDS failover: app retry storm prolonged outage

| Field | Value |
|-------|--------|
| **Severity** | SEV-1 |
| **Environment** | production |
| **Window** | `2026-02-20T11:05Z` → `2026-02-20T11:58Z` |
| **Status** | resolved |

## Executive summary

AWS **RDS Multi-AZ failover** completed in **~90 s** (within spec), but hundreds of app instances **immediately** opened max connection attempts with **zero backoff**. Writer was **saturated** accepting handshakes; legitimate traffic could not attach. **Effective** outage extended well past engine failover.

## Impact

- **~53 minutes** customer-visible DB errors vs **~2 min** engine role change.
- Peak connection count **3×** normal.

## Timeline (UTC)

| Time | Event |
|------|--------|
| 11:05 | RDS failover notification |
| 11:07 | Engine healthy; apps still erroring |
| 11:15 | Identified connection **retry storm** in metrics |
| 11:30 | **Circuit** opened at gateway; staged app restart with **jitter** |
| 11:58 | Connections normalised |

## Detection

RDS event + error rate; confusion until connection graph reviewed.

## Root cause

**Client resilience** anti-pattern: tight retry loop on `connection refused` during DNS/endpoint propagation.

## Resolution

Exponential backoff + **jitter** on connect; **max** reconnect concurrency; validated with chaos test.

## Runbooks

- **Primary:** `RB-DB-CONN-004` — `docs/runbooks/runbook-04-database-connection-exhaustion.md`
- **Related:** `RB-HTTP-5XX-003`

```json
{
  "incident_id": "INC-016",
  "severity": "CRITICAL",
  "primary_runbook_ids": ["RB-DB-CONN-004"],
  "related_runbook_ids": ["RB-HTTP-5XX-003"],
  "services_affected": ["rds-primary", "all-consumers"],
  "symptoms": ["failover", "connection_storm", "extended_outage"],
  "root_cause_category": "software_defect",
  "expected_triage_severity": "CRITICAL",
  "expected_escalate": true
}
```
