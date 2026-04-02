# Sample log bundles (conventions)

**Purpose:** Synthetic **application-style** log excerpts for RAG, triage agents, and evaluation. They are **not** raw vendor exports — see [Real cloud log formats](#real-cloud-log-formats) below.

**Maintainer:** Oluwatosin Jegede  
**Last updated:** 2026-04-02

---

## Format conventions (this folder)

| Element | Convention |
|---------|------------|
| **Timestamp** | RFC 3339 UTC (`2026-04-10T14:05:01Z`) |
| **Line shape** | `TIMESTAMP LEVEL [component] message key=value ...` |
| **Levels** | `DEBUG`, `INFO`, `WARN`, `ERROR` (Syslog-ish) |
| **Components** | Logical subsystems (`kubelet`, `payment-api`, `coredns`) — not always one process |
| **PII** | Use synthetic IDs (`req_87123`, `txn_5521`) only |

**Optional future variant:** append `.jsonl` siblings with `{"ts":"...","level":"...",...}` for the same scenarios (easier for structured parsers).

---

## Real cloud log formats (what production looks like)

These files **intentionally** read like **merged narratives** (app + platform + “metrics” pseudo-lines). In production you usually have:

- **AWS ALB:** Access logs (S3) — tab-delimited fields, `elb_status_code`, `target_status_code`, `request_processing_time`, not prose.
- **CloudWatch Logs:** Often **JSON** per line from Lambda/ECS, or **container stdout** with your app’s format.
- **Kubernetes:** `kubectl logs` = container stdout; **events** from `kubectl get events` are a separate stream (`FailedMount`, `Failed`, `PullBackOff`).
- **RDS / Postgres:** `FATAL`, `ERROR` in PostgreSQL CSV/text logs; connection counts from **Performance Insights / CloudWatch metrics**, not always inline with app logs.

Use this folder for **semantic** training; wire **Phase 8** evals to confirm the agent still reasons when given JSONL or ALB-style snippets.

---

## Catalog: log file → incident → runbooks

| Log file | Incident (see `data/incidents/`) | Primary runbook ID(s) |
|----------|-----------------------------------|------------------------|
| `high-cpu-payment-api.log` | Themes: INC-001, INC-008, `sample-runbook-01` | `RB-PAYMENT-API-HIGH-CPU-001`, `RB-EXT-API-008`, `RB-GEN-HIGH-CPU-001` |
| `alb-unhealthy-targets.log` | INC-003 | `RB-LB-HEALTH-010`, `RB-HTTP-5XX-003` |
| `blue-green-routing-failure.log` | INC-020 | `RB-LB-HEALTH-010`, `RB-HTTP-5XX-003` |
| `crashloop-missing-secret-auth-service.log` | INC-005 | `RB-K8S-CRASH-005` |
| `db-connection-exhaustion-orders-service.log` | INC-004 | `RB-DB-CONN-004` |
| `disk-saturation-logging-service.log` | INC-006 (content: `inventory-api` trace / node ephemeral disk) | `RB-DISK-SAT-006` |
| `external-api-latency-cascade.log` | INC-008 | `RB-EXT-API-008` |
| `imagepullbackoff-registry-failure.log` | INC-011 | `RB-K8S-CRASH-005` (closest) |
| `kubernetes-dns-resolution-failure.log` | INC-015 | `RB-EXT-API-008` (+ future DNS runbook) |
| `memory-oom-notification-service.log` | INC-002 | `RB-MEM-OOM-002`, `RB-QUEUE-LAG-009` |
| `queue-backlog-worker-lag.log` | INC-009 | `RB-QUEUE-LAG-009`, `RB-DB-CONN-004` |
| `rds-failover-retry-storm.log` | INC-016 | `RB-DB-CONN-004` |
| `tls-handshake-failure-internal-services.log` | INC-017 (mTLS / incomplete chain) | `RB-TLS-CERT-007` |
| `edge-tls-certificate-expired.log` | INC-007 (public / edge expiry) | `RB-TLS-CERT-007`, `RB-LB-HEALTH-010` |
| `noisy-neighbor-node-contention.log` | INC-018 | `RB-GEN-HIGH-CPU-001`, `RB-PAYMENT-API-HIGH-CPU-001` |
| `secrets-rotation-credential-drift.log` | (rotation / stale pods) | `RB-K8S-CRASH-005`, `RB-DB-CONN-004` |
| `cross-region-failover-split-brain.log` | Training: DR/routing | `RB-LB-HEALTH-010`, `RB-EXT-API-008` |
| `hidden-dependency-failure-cache-layer.log` | Training: cache / SLO blind spot | `RB-EXT-API-008`, `RB-HTTP-5XX-003` |
| `partial-data-corruption-ledger-service.log` | Training: integrity / recon | Link finance runbooks when added |
| `monitoring-false-positive-alert-storm.log` | Training: no customer impact | Observability / alert hygiene |
| `observability-gap-missing-logs.log` | Training: blind triage | `RB-K8S-CRASH-005`, `RB-DB-CONN-004` |

---

## How to add a new bundle

1. Pick a **scenario** already described in an incident or runbook (or add both).
2. Keep **one primary failure mode** per file where possible (avoid mixing unrelated TLS errors).
3. Add a row to the **catalog** table above.
4. Prefer **actionable** lines ops would grep (`OOMKilled`, `too many connections`, `ImagePullBackOff`, `certificate has expired`).

---

## Related paths

- Incidents: `data/incidents/sample-incident.md`
- Runbooks: `data/runbooks/`
