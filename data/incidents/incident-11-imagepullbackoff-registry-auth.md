# INC-011 — ImagePullBackOff after ECR IAM policy tighten

| Field | Value |
|-------|--------|
| **Severity** | SEV-2 |
| **Environment** | production |
| **Window** | `2026-03-10T17:22Z` → `2026-03-10T18:05Z` |
| **Status** | resolved |

## Executive summary

A **least-privilege** change removed `ecr:GetDownloadUrlForLayer` for the **node instance role** used by self-managed workers (legacy). New pods could not pull images; status **ImagePullBackOff**. Existing pods kept running until rescheduled.

## Impact

- **New** deployments and **HPA** scale-out failed; **no** immediate user impact until churn.
- Risk of **slow bleed** as nodes cycled — mitigated within ~43 minutes.

## Timeline (UTC)

| Time | Event |
|------|--------|
| 17:22 | Failed rollout; events `Failed to pull image` `403` |
| 17:30 | Correlated with IAM change merge 25 min prior |
| 17:45 | Restored ECR read policy to role; verified pull from test pod |
| 18:05 | Rollout succeeded |

## Detection

ArgoCD sync failure + kube events.

## Root cause

**IAM change** tested on **managed** nodes only; legacy ASG role differed.

## Resolution

Policy fix; inventory all **pull identities**; add **pre-merge** checklist for ECR consumers.

## Runbooks

- **Primary:** `RB-K8S-CRASH-005` — `data/runbooks/runbook-05-kubernetes-crashloopbackoff.md` *(closest: startup/pull failures; see runbook “Out of scope: ImagePullBackOff” — treat as registry/IAM.)*
- **Related:** `RB-LB-HEALTH-010` (if scale-out needed healthy pulls)

> **Note:** Consider adding `runbook-XX-imagepullbackoff-ecr.md` when you expand the library.

```json
{
  "incident_id": "INC-011",
  "severity": "HIGH",
  "primary_runbook_ids": ["RB-K8S-CRASH-005"],
  "related_runbook_ids": ["RB-LB-HEALTH-010"],
  "services_affected": ["eks-workers", "multiple-deployments"],
  "symptoms": ["imagepullbackoff", "ecr_403", "deploy_failure"],
  "root_cause_category": "misconfiguration",
  "expected_triage_severity": "HIGH",
  "expected_escalate": true
}
```
