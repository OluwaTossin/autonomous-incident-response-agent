# INC-014 — ECS tasks exit: wrong `NODE_OPTIONS` max-old-space-size vs task memory

| Field | Value |
|-------|--------|
| **Severity** | SEV-2 |
| **Environment** | production |
| **Window** | `2026-03-28T09:10Z` → `2026-03-28T09:55Z` |
| **Status** | resolved |

## Executive summary

Task definition set **hard memory** to **512 MiB** but `NODE_OPTIONS=--max-old-space-size=1024`. Node attempted heap above cgroup limit; ECS agent **OOM-killed** tasks in a loop. Service **desired count** never stabilised.

## Impact

- **Intermittent** availability for `notifications-api` (~45 min) during peak morning traffic.
- Similar symptom family to K8s OOM but on **ECS Fargate**.

## Timeline (UTC)

| Time | Event |
|------|--------|
| 09:10 | Service cycling; stopped reason `OutOfMemoryError` / OOM |
| 09:22 | Compared task memory to `NODE_OPTIONS` |
| 09:35 | Set heap to **~75%** of task memory per standard; redeployed |
| 09:55 | Steady state |

## Detection

ECS service events + CloudWatch alarms on running count.

## Root cause

**Copy-paste** task def from larger task size; **no** validation in pipeline.

## Resolution

Correct env; add **lint** in CDK for heap ≤ 0.75 × task memory.

## Runbooks

- **Primary:** `RB-MEM-OOM-002` — `docs/runbooks/runbook-02-memory-pressure-oom.md`
- **Related:** `RB-K8S-CRASH-005` *(analogous crash/restart loop patterns)*

```json
{
  "incident_id": "INC-014",
  "severity": "HIGH",
  "primary_runbook_ids": ["RB-MEM-OOM-002"],
  "related_runbook_ids": ["RB-K8S-CRASH-005"],
  "services_affected": ["notifications-api", "ecs-fargate"],
  "symptoms": ["task_exit", "oom", "ecs_restart_loop"],
  "root_cause_category": "misconfiguration",
  "expected_triage_severity": "HIGH",
  "expected_escalate": true
}
```
