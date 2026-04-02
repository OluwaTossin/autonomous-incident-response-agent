# INC-018 — Noisy neighbour: burstable instance CPU credit exhaustion

| Field | Value |
|-------|--------|
| **Severity** | SEV-2 |
| **Environment** | production |
| **Window** | `2026-02-11T19:30Z` → `2026-02-11T21:10Z` |
| **Status** | resolved |

## Executive summary

Several **burstable** (T-class) instances co-located workloads: a **batch** job spiked CPU on shared nodes. `payment-api` pods on same nodes hit **CPU credit** exhaustion and **throttled** despite “low” average cluster CPU. Latency SLO burned **without** clear deploy correlation.

## Impact

- **Payment** p99 elevated for **~100 minutes**; **no** large 5xx spike (throttling not hard fail).
- Subset of users saw **timeouts** on mobile.

## Timeline (UTC)

| Time | Event |
|------|--------|
| 19:30 | Regional latency SLO burn, no new deploy |
| 19:50 | Node-level: **CPUCreditBalance** near zero on affected nodes |
| 20:15 | **Cordon** + drain noisy batch nodes; moved batch to **dedicated** pool |
| 21:10 | Latency recovered |

## Detection

Latency + node exporter **steal** / AWS credit metrics.

## Root cause

**Placement** policy allowed batch on same instance class as latency-sensitive tier; **no** taint/toleration separation.

## Resolution

Dedicated node group for batch; **taint** `workload=batch`; payment on **non-burstable** or guaranteed pool.

## Runbooks

- **Primary:** `RB-GEN-HIGH-CPU-001` — `docs/runbooks/runbook-01-high-cpu-usage.md`
- **Related:** `RB-PAYMENT-API-HIGH-CPU-001`, `sample-runbook-01.md`

```json
{
  "incident_id": "INC-018",
  "severity": "HIGH",
  "primary_runbook_ids": ["RB-GEN-HIGH-CPU-001", "RB-PAYMENT-API-HIGH-CPU-001"],
  "related_runbook_ids": [],
  "services_affected": ["payment-api", "batch-jobs"],
  "symptoms": ["latency", "cpu_throttle", "burstable_credits"],
  "root_cause_category": "capacity",
  "expected_triage_severity": "HIGH",
  "expected_escalate": true
}
```
