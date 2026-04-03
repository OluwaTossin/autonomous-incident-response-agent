# Runbook: High CPU on `payment-api` (production)

**Runbook ID:** RB-PAYMENT-API-HIGH-CPU-001  
**Service:** `payment-api`  
**Environment:** Production (adapt checks for staging)  
**Primary owner:** Service team owning payments rail  
**Supporting:** Platform / SRE (capacity, cluster, networking)  
**Severity when triggered:** Typically HIGH (CRITICAL if combined with elevated 5xx, auth failures, or payment success-rate SLO breach)  
**Last updated:** 2026-04-02 — Oluwatosin Jegede (review quarterly or after major incidents)

---

## Summary

This runbook covers **sustained or sudden high CPU** on the payment API tier. Goal: determine whether load, a bad deploy, dependency latency, or misconfiguration is responsible; stabilise customer impact; and escalate with **time-bounded evidence** (graphs, queries, deployment correlation).

---

## Scope and applicability

**In scope:** Linux containers or VMs running `payment-api`, Kubernetes CPU metrics, application process CPU, correlation with latency and errors.

**Out of scope (use other runbooks):** Pure memory pressure / OOM → `runbook-02-memory-pressure-oom.md`. HTTP 5xx without CPU story → `runbook-03-http-5xx-spike.md`. DB pool exhaustion → `runbook-04-database-connection-exhaustion.md`.

**Related:** Generic high-CPU patterns → `runbook-01-high-cpu-usage.md`.

---

## Symptoms and typical alerts

- Alert title or labels: “CPU”, “saturation”, “throttling”, “high utilisation”, `container_cpu_usage_seconds_total`, `CPUThrottlingHigh`.
- Dashboards: CPU high on all or subset of replicas; queue depth or goroutine/thread count up; p95/p99 latency elevated.
- Logs: slow request traces, timeouts, repeated expensive handlers, N+1 query patterns (if logged).

---

## Preconditions

- [ ] **Read-only** production metrics/logs access, or approved break-glass.
- [ ] Current **deployment identity**: image digest or tag, config version, feature-flag snapshot if applicable.
- [ ] **Escalation matrix** and current on-call (payments + platform).
- [ ] Known **change window**: deploys, marketing events, partner load tests.

---

## Customer impact and blast radius (first 5 minutes)

| Question | Why it matters |
|----------|----------------|
| Are **5xx** or **payment decline** rates elevated vs baseline? | Drives severity and whether to invoke incident commander / comms. |
| Single AZ/region or **global**? | Failover and stakeholder scope. |
| **PCI / fraud** signals anomalous (velocity, auth)? | May require security path, not only scale-out. |

Document **approximate % of traffic or $ at risk** when observability supports it.

---

## Immediate checks (first 5 minutes)

1. **Scope** — CPU high on **all** replicas vs one node (noisy neighbour, bad instance type, tainted node)?  
2. **Temporal correlation** — Deploy, flag flip, cache purge, or traffic spike within the same window?  
3. **Traffic and errors** — RPS, p95/p99, **5xx**, timeout rate. If errors track CPU, treat as **customer-impacting**.  
4. **Dependencies** — DB slow queries, cache timeouts, partner HTTP latency. **Retry storms** often inflate CPU.  
5. **Mitigations (change-control)** — Horizontal scale if caps allow; prepare **rollback** if release-correlated; avoid ad-hoc prod edits without ticket/approval.

---

## Deeper diagnosis (next 15–30 minutes)

| Area | What to inspect |
|------|------------------|
| **Runtime / profiler** | Flame graph, hot stacks, GC pressure if applicable. |
| **Database** | Slow query log, connection wait, locks, missing index on new code path. |
| **Cache** | Hit ratio, stampede after TTL, large key payloads. |
| **Feature flags** | New path enabled for large cohort. |
| **Platform** | CPU requests vs limits (throttling), burstable instance credits, CFS quotas. |
| **Upstream** | WAF / API gateway rate patterns, abusive client (coordinate before blocking). |

Capture **UTC timestamps**, dashboard links, and log query IDs in the incident record.

---

## Likely root causes (hypotheses — verify with data)

1. Legitimate **traffic spike** or partner integration.  
2. **Regressing release** — hot path, serialization, missing index.  
3. **Dependency degradation** — threads/workers pile up waiting on I/O.  
4. **Misconfiguration** — pool sizes, debug logging at volume in prod.  
5. **Infrastructure** — undersized nodes, throttling, noisy neighbour on shared tenancy.

---

## Recommended remediation (ordered)

1. **Stabilise impact:** scale out (within policy), rate-limit if abuse confirmed, **rollback** if deploy-correlated and approved.  
2. **Reduce avoidable load:** tone down diagnostic logging only with observability owner alignment.  
3. **Track defect** if regression confirmed; attach profiler/query evidence.  
4. **Capacity / SRE review** if growth-driven; update autoscaling bounds and alerts.

---

## Escalation criteria

Escalate **immediately** if:

- Payment **SLO/SLA** or success-rate threshold breached.  
- **Fraud, data integrity, or security** anomaly suspected.  
- No stabilisation within **agreed timebox** (define in escalation matrix).  
- **Access gap** — single responder cannot reach prod tools; page platform/security.

Otherwise: update incident **every 15 minutes** until resolved or escalated.

---

## Communication and status updates

- Internal: incident channel + ticket; note **customer-visible or not**.  
- External/comms: only per **comms playbook** and legal/compliance if payment-impacting.  
- Post stabilisation: short **timeline + impact + next steps** in ticket.

---

## Recovery verification

- [ ] CPU within expected band for current load profile.  
- [ ] Error rate and latency at baseline for **two** alert evaluation windows.  
- [ ] No new related **SEV** pages.  
- [ ] Ticket updated: root cause (confirmed or leading hypothesis), actions taken, follow-up tasks.

---

## Post-incident

- [ ] Customer-impacting → **blameless postmortem** per policy.  
- [ ] Close gaps: dashboards, SLO alerts, runbook links, canary/rollback guardrails.

---

## Related documents

- Generic CPU: `runbook-01-high-cpu-usage.md`  
- Escalation matrix: `docs/decisions/escalation-matrix.md` (create when ready)  
- Service catalog: `docs/architecture/service-catalog.md` (create when ready)

---

## Evidence to capture

- Deployment / image identifiers and change tickets.  
- CPU, RPS, error-rate, latency graphs (UTC range).  
- Top log patterns or trace samples (redact PII/PCI).  
- Any scale/rollback actions with timestamps and approver.

---

## Metadata for RAG / automation

```yaml
runbook_id: RB-PAYMENT-API-HIGH-CPU-001
service: payment-api
symptoms: [high_cpu, latency, possible_5xx, payment_errors]
environments: [production, staging]
tags: [cpu, performance, payments, api, slo]
related_runbooks: [runbook-01-high-cpu-usage, runbook-03-http-5xx-spike, runbook-04-database-connection-exhaustion]
```
