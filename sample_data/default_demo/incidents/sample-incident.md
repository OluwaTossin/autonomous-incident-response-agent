# Sample incident record (template)

Use this structure for **historical incidents**, **training data**, and **evaluation gold labels**. Keep **PII and secrets out** of samples; use synthetic service names.

**Maintainer:** Oluwatosin Jegede  
**Last updated:** 2026-04-02

---

## How this ties to runbooks

Each incident should cite at least one **`Runbook ID`** from `data/runbooks/` (e.g. `RB-HTTP-5XX-003`). That lets RAG and triage agents retrieve **procedure** alongside **past narrative**.

| Runbook ID | Document |
|------------|----------|
| `RB-PAYMENT-API-HIGH-CPU-001` | `data/runbooks/sample-runbook-01.md` |
| `RB-GEN-HIGH-CPU-001` | `runbook-01-high-cpu-usage.md` |
| `RB-MEM-OOM-002` | `runbook-02-memory-pressure-oom.md` |
| `RB-HTTP-5XX-003` | `runbook-03-http-5xx-spike.md` |
| `RB-DB-CONN-004` | `runbook-04-database-connection-exhaustion.md` |
| `RB-K8S-CRASH-005` | `runbook-05-kubernetes-crashloopbackoff.md` |
| `RB-DISK-SAT-006` | `runbook-06-disk-storage-saturation.md` |
| `RB-TLS-CERT-007` | `runbook-07-ssl-tls-certificate-expiry.md` |
| `RB-EXT-API-008` | `runbook-08-external-api-dependency-failure.md` |
| `RB-QUEUE-LAG-009` | `runbook-09-queue-backlog-worker-lag.md` |
| `RB-LB-HEALTH-010` | `runbook-10-load-balancer-unhealthy-targets.md` |

---

## Markdown template (copy for new incidents)

### Header metadata

| Field | Value |
|-------|--------|
| **Incident ID** | INC-XXX |
| **Title** | Short imperative description |
| **Severity** | SEV-1 / SEV-2 / SEV-3 (or CRITICAL–LOW) |
| **Environment** | production / staging |
| **Status** | resolved / mitigated |
| **Window** | `2026-04-02T14:00:00Z` → `2026-04-02T15:12:00Z` (UTC) |

### Executive summary

Two to four sentences: what broke, who was affected, how it ended.

### Impact

- **Customer / business:** …
- **SLIs:** error rate, latency, success rate (qualitative or %).
- **Duration:** X minutes to mitigate, Y minutes to full recovery.

### Timeline (UTC)

| Time | Event |
|------|--------|
| T+0 | Detection / page |
| … | Key investigation or decision |
| T+n | Mitigation verified |

### Detection

Alert names, dashboard, or customer report — what fired first.

### Root cause (confirmed or leading hypothesis)

Single paragraph. Distinguish **trigger** vs **why it was possible** (guardrails gap).

### Contributing factors

- e.g. missing canary, weak health check, on-call access gap.

### Resolution

Ordered actions actually taken (rollback, scale, config fix).

### Runbooks

- **Primary:** `RB-…` — …
- **Related:** `RB-…`, `RB-…`

### Lessons learned / actions

- [ ] Action owner + due date style items.

---

## Optional: machine-readable block (for APIs / eval harness)

Place at the bottom of the same file or in `data/incidents/` JSONL.

```json
{
  "incident_id": "INC-XXX",
  "severity": "HIGH",
  "primary_runbook_ids": ["RB-HTTP-5XX-003"],
  "related_runbook_ids": ["RB-LB-HEALTH-010"],
  "services_affected": ["example-api"],
  "symptoms": ["5xx_spike", "alb_unhealthy_targets"],
  "root_cause_category": "misconfiguration",
  "expected_triage_severity": "HIGH",
  "expected_escalate": true
}
```

---

## File naming

`incident-NN-short-slug.md` — numeric prefix keeps sort order stable for datasets. In this repo, incident markdown lives under **`data/incidents/`** (per [`docs/build-journey/execution-v1.md`](../../docs/build-journey/execution-v1.md)).

---

## Catalog (synthetic dataset in this repo)

| File | ID | Primary runbook(s) |
|------|-----|-------------------|
| `incident-01-high-cpu-post-deployment.md` | INC-001 | `RB-GEN-HIGH-CPU-001` |
| `incident-02-memory-leak-oomkills.md` | INC-002 | `RB-MEM-OOM-002` |
| `incident-03-http-503-unhealthy-targets.md` | INC-003 | `RB-LB-HEALTH-010` |
| `incident-04-database-connection-exhaustion.md` | INC-004 | `RB-DB-CONN-004` |
| `incident-05-kubernetes-missing-secret-crashloop.md` | INC-005 | `RB-K8S-CRASH-005` |
| `incident-06-disk-saturation-log-explosion.md` | INC-006 | `RB-DISK-SAT-006` |
| `incident-07-tls-certificate-expiry-failure.md` | INC-007 | `RB-TLS-CERT-007` |
| `incident-08-external-api-latency-cascade.md` | INC-008 | `RB-EXT-API-008` |
| `incident-09-queue-backlog-downstream-slow.md` | INC-009 | `RB-QUEUE-LAG-009` |
| `incident-10-load-balancer-routing-misconfig.md` | INC-010 | `RB-LB-HEALTH-010` |
| `incident-11-imagepullbackoff-registry-auth.md` | INC-011 | `RB-K8S-CRASH-005` (closest) |
| `incident-12-alb-504-timeout-db-latency.md` | INC-012 | `RB-HTTP-5XX-003` |
| `incident-13-rds-low-storage-write-failure.md` | INC-013 | `RB-DISK-SAT-006` |
| `incident-14-ecs-task-exit-runtime-config.md` | INC-014 | `RB-MEM-OOM-002` |
| `incident-15-cluster-dns-degradation-auth-failure.md` | INC-015 | `RB-EXT-API-008` |
| `incident-16-rds-failover-retry-amplification.md` | INC-016 | `RB-DB-CONN-004` |
| `incident-17-mtls-certificate-chain-mismatch.md` | INC-017 | `RB-TLS-CERT-007` |
| `incident-18-noisy-neighbor-resource-contention.md` | INC-018 | `RB-GEN-HIGH-CPU-001`, `RB-PAYMENT-API-HIGH-CPU-001` |
| `incident-19-stale-configmap-inconsistent-behavior.md` | INC-019 | `RB-K8S-CRASH-005` |
| `incident-20-blue-green-stickiness-routing-failure.md` | INC-020 | `RB-LB-HEALTH-010` |
