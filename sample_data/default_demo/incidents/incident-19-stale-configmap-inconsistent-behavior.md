# INC-019 — Stale ConfigMap: pods on two revisions during rolling update

| Field | Value |
|-------|--------|
| **Severity** | SEV-2 |
| **Environment** | production |
| **Window** | `2026-04-02T07:15Z` → `2026-04-02T08:40Z` |
| **Status** | resolved |

## Executive summary

A **ConfigMap** update did **not** trigger rolling restart (hash not wired in pod template). **Half** the pods served **feature flag** `rollout-new-parser=true`, half `false`. **A/B** behaviour at random caused **10%** of requests to hit incompatible code path → **500** on specific JSON payloads.

## Impact

- **Intermittent** 500 (~10% sample rate) for **~85 minutes**; hard to reproduce locally.
- Support could “reproduce” by retrying same request (different pod).

## Timeline (UTC)

| Time | Event |
|------|--------|
| 07:15 | Error spike on single API version |
| 07:35 | Compared pod env from two endpoints — **ConfigMap version drift** |
| 07:50 | Forced **rollout restart** after CM change |
| 08:40 | Error rate zero |

## Detection

5xx rate + distributed trace showing **different build flags** (added after incident).

## Root cause

**Immutable ConfigMap** pattern not used; **no** automatic restart on CM change.

## Resolution

Annotate pod template with **checksum/config**; Reloader or equivalent; integration test for **single** config revision during deploy.

## Runbooks

- **Primary:** `RB-K8S-CRASH-005` — `data/runbooks/runbook-05-kubernetes-crashloopbackoff.md` *(config/consistency)*  
- **Related:** `RB-HTTP-5XX-003`

```json
{
  "incident_id": "INC-019",
  "severity": "HIGH",
  "primary_runbook_ids": ["RB-K8S-CRASH-005"],
  "related_runbook_ids": ["RB-HTTP-5XX-003"],
  "services_affected": ["ingestion-api"],
  "symptoms": ["intermittent_500", "config_drift", "split_brain_behavior"],
  "root_cause_category": "misconfiguration",
  "expected_triage_severity": "HIGH",
  "expected_escalate": true
}
```
