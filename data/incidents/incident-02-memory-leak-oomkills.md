# INC-002 — OOMKilled pods on `search-indexer` workers

| Field | Value |
|-------|--------|
| **Severity** | SEV-2 |
| **Environment** | production |
| **Window** | `2026-02-04T22:01Z` → `2026-02-05T00:18Z` |
| **Status** | resolved |

## Executive summary

Worker pods processing bulk reindex jobs accumulated **unbounded in-memory buffers** after a library upgrade. Kubernetes repeatedly **OOMKilled** containers; queue lag grew until replicas were rolled back and a patch deployed.

## Impact

- Search freshness delayed up to **~2 h** for non-critical indices; **no** search outage (read path served stale shards).
- ~15% of batch jobs failed and retried.

## Timeline (UTC)

| Time | Event |
|------|--------|
| 22:01 | `OOMKilled` spike, `ApproximateAgeOfOldestMessage` rising |
| 22:15 | Identified **monotonic RSS** growth per pod over 40 min |
| 22:40 | Rolled image to **previous** digest |
| 00:18 | Patched release with streaming parser; lag drained |

## Detection

Kube events + SQS age-of-oldest-message alert.

## Root cause

Parser upgrade loaded entire **multi-GB** batch into heap instead of streaming; limit was below worst-case payload size.

## Resolution

Rollback image; fix streaming; raised **memory request** slightly after load proof; added **growth** alert on container memory derivative.

## Runbooks

- **Primary:** `RB-MEM-OOM-002` — `data/runbooks/runbook-02-memory-pressure-oom.md`
- **Related:** `RB-K8S-CRASH-005`, `RB-QUEUE-LAG-009`

```json
{
  "incident_id": "INC-002",
  "severity": "HIGH",
  "primary_runbook_ids": ["RB-MEM-OOM-002"],
  "related_runbook_ids": ["RB-K8S-CRASH-005", "RB-QUEUE-LAG-009"],
  "services_affected": ["search-indexer"],
  "symptoms": ["oomkilled", "restart_loop", "queue_lag"],
  "root_cause_category": "software_defect",
  "expected_triage_severity": "HIGH",
  "expected_escalate": true
}
```
