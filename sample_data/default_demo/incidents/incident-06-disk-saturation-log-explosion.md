# INC-006 — Node `DiskPressure`: debug logging left on in hot path

| Field | Value |
|-------|--------|
| **Severity** | SEV-2 |
| **Environment** | production |
| **Window** | `2026-02-14T08:30Z` → `2026-02-14T11:05Z` |
| **Status** | resolved |

## Executive summary

A **troubleshooting** flag enabled **TRACE**-level logging for `inventory-api` in production and was not reverted. Ephemeral volume on nodes filled; kubelet set **`DiskPressure`**; pods were **evicted**, causing churn and errors.

## Impact

- **Evictions** on 3 nodes; brief **503** bursts during rescheduling.
- Log volume **~400 GB** accumulated over 36 h before threshold.

## Timeline (UTC)

| Time | Event |
|------|--------|
| 08:30 | `DiskPressure` + pod evictions |
| 09:00 | Traced largest consumer: `inventory-api` log files on emptyDir |
| 09:45 | Disabled trace flag; rotated logs with SRE approval |
| 11:05 | Node pressure cleared; cluster autoscaler replaced worst node |

## Detection

Node condition alert + eviction events.

## Root cause

**Break-glass** change without **ticket** or **TTL**; no automated revert; logging to local disk without rotation bound in that build.

## Resolution

Revert log level; enforce **max log size** in chart; break-glass requires **expire-at** annotation.

## Runbooks

- **Primary:** `RB-DISK-SAT-006` — `data/runbooks/runbook-06-disk-storage-saturation.md`
- **Related:** `RB-K8S-CRASH-005`, `RB-LB-HEALTH-010`

```json
{
  "incident_id": "INC-006",
  "severity": "HIGH",
  "primary_runbook_ids": ["RB-DISK-SAT-006"],
  "related_runbook_ids": ["RB-K8S-CRASH-005", "RB-LB-HEALTH-010"],
  "services_affected": ["inventory-api", "eks-nodes"],
  "symptoms": ["disk_pressure", "pod_eviction", "log_explosion"],
  "root_cause_category": "operational_error",
  "expected_triage_severity": "HIGH",
  "expected_escalate": true
}
```
