# INC-005 — CrashLoop: rotated secret name mismatch in Deployment

| Field | Value |
|-------|--------|
| **Severity** | SEV-2 |
| **Environment** | production |
| **Window** | `2026-03-01T11:40Z` → `2026-03-01T12:28Z` |
| **Status** | resolved |

## Executive summary

Secrets rotation job created `api-keys-v3` and removed `api-keys-v2`. The **Deployment** still referenced `api-keys-v2`; new pods failed mount, exited **1**, entered **CrashLoopBackOff**. Rollout stalled at 60% new ReplicaSet.

## Impact

- **Degraded** capacity: 40% of pods on old RS healthy; 60% crash-looping.
- Elevated latency; **no** complete outage due to partial old fleet.

## Timeline (UTC)

| Time | Event |
|------|--------|
| 11:40 | Rollout stuck, restart storm |
| 11:45 | `kubectl describe pod`: `CreateContainerConfigError` / secret not found |
| 11:52 | Patched Deployment to `api-keys-v3` |
| 12:28 | Rollout complete; readiness stable |

## Detection

Kube `RolloutProgressing=False` + error rate.

## Root cause

**Rotation runbook** updated K8s Secret object but **not** the Deployment manifest in Git; ArgoCD auto-sync was disabled on that app (manual drift).

## Resolution

Fix envFrom reference; re-enable sync; add **pre-delete** check that no Deployment references old secret name.

## Runbooks

- **Primary:** `RB-K8S-CRASH-005` — `data/runbooks/runbook-05-kubernetes-crashloopbackoff.md`
- **Related:** `RB-HTTP-5XX-003`

```json
{
  "incident_id": "INC-005",
  "severity": "HIGH",
  "primary_runbook_ids": ["RB-K8S-CRASH-005"],
  "related_runbook_ids": ["RB-HTTP-5XX-003"],
  "services_affected": ["bff-api"],
  "symptoms": ["crashloopbackoff", "secret_not_found", "rollout_stuck"],
  "root_cause_category": "misconfiguration",
  "expected_triage_severity": "HIGH",
  "expected_escalate": true
}
```
