# Runbook: High CPU usage (generic application tier)

**Runbook ID:** RB-GEN-HIGH-CPU-001  
**Service:** Any stateless API, worker, or web tier (not database nodes — use DB-specific runbooks)  
**Environment:** Production / staging  
**Primary owner:** Owning service team  
**Supporting:** Platform / SRE  
**Severity when triggered:** LOW–HIGH depending on error rate, capacity headroom, and SLO (see below)  
**Last updated:** 2026-04-02 — Oluwatosin Jegede

---

## Summary

**High CPU** means sustained or spiky processor utilisation that risks latency, throttling, or exhaustion of CPU quota. This runbook is **service-agnostic**. For payment-specific APIs, use **`sample-runbook-01.md`** in addition.

---

## Scope and applicability

**In scope:** Application containers/VMs, process-level CPU, Kubernetes `cpu` metrics, correlation with load and errors.

**Out of scope:** Database **CPU as primary** symptom → involve DBA / `runbook-04-database-connection-exhaustion.md` and infra DB runbooks. Pure **memory / OOM** → `runbook-02-memory-pressure-oom.md`.

---

## Symptoms and typical alerts

- Prometheus/Datadog-style: `CPUUtilizationHigh`, `container_cpu_cfs_throttled_seconds`, saturation alerts.
- Dashboards: user vs system CPU, per-pod skew, node-level contention.
- User-visible: latency up without proportional traffic (often I/O wait masked — verify).

---

## Preconditions

- [ ] Metrics and logs access; know **service name**, **namespace/cluster**, **deployment version**.
- [ ] Autoscaling policy (HPA/KEDA/ASG) and **max replica** caps.
- [ ] On-call routing for service + platform.

---

## Severity guidance (triage)

| Level | Indicators |
|-------|------------|
| **LOW** | Elevated CPU, SLO green, plenty of headroom, no customer complaints. |
| **MEDIUM** | CPU high but redundancy OK; latency slightly elevated. |
| **HIGH** | Throttling, shedding, or latency SLO at risk; partial degradation. |
| **CRITICAL** | Wide outage, SLO breach, or cascade (e.g. retry storm). |

---

## Immediate checks (first 5 minutes)

1. **Uniform vs subset** — All replicas hot vs one bad node or bad AZ?  
2. **Deploy / config / flag** — Change in last N minutes?  
3. **Traffic** — Organic spike, bot, or misconfigured client retry loop?  
4. **Errors** — 5xx or timeout correlation → bias to higher severity and `runbook-03-http-5xx-spike.md`.  
5. **Throttling** — If `throttled` time is non-zero, check **limits vs requests** before blaming code.

---

## Deeper diagnosis (15–30 minutes)

| Area | Actions |
|------|---------|
| **Profiling** | Continuous profiler or sampled traces; identify hot methods. |
| **Dependencies** | DB, cache, HTTP clients — latency and error correlation. |
| **GC / runtime** | For JVM/Go/Node: pause times, allocation rate (if applicable). |
| **Batch/cron** | Overlapping jobs doubling CPU with user traffic. |
| **Platform** | Node pressure, descheduling, instance family limits. |

---

## Likely root causes

1. Traffic or batch load increase.  
2. New release regression or inefficient query/path.  
3. Upstream/downstream slowness → worker pool saturation → CPU spin/wait patterns.  
4. Tight CPU limits + legitimate load.  
5. Log/metric cardinality or debug logging in hot path.

---

## Recommended remediation (ordered)

1. **Scale horizontally** if within policy and caps.  
2. **Rollback or disable flag** if strongly correlated with release (approved change).  
3. **Throttle abusive clients** via gateway/WAF with security/compliance review.  
4. **Tune resources** (requests/limits) after evidence — avoid permanent “fix” by unlimited CPU without cost review.  
5. **File defect** with profiler output for engineering backlog.

---

## Escalation criteria

- SLO breach or **major** customer impact.  
- No clear lever after **timeboxed** investigation (e.g. 30 min).  
- Suspected **security** (mining, compromise) — page security incident process.  
- Platform-wide (many services) — likely cluster/infrastructure incident.

---

## Communication and status updates

Incident ticket + chat; **15-minute** updates while SEV active. Note whether impact is **external**.

---

## Recovery verification

- [ ] CPU and latency within baseline for load.  
- [ ] No throttling alerts for **two** evaluation periods (tune to the stack).  
- [ ] Autoscaler stable (no flapping).

---

## Post-incident

- [ ] Add capacity tests or load test for similar peaks.  
- [ ] Improve alert thresholds to separate “noisy” from “SLO risk”.  
- [ ] Link dependent runbooks from service catalog.

---

## Evidence to capture

Time-range graphs (UTC), deployment IDs, HPA events, top endpoints or jobs by CPU, redacted log samples.

---

## Metadata for RAG / automation

```yaml
runbook_id: RB-GEN-HIGH-CPU-001
service: generic_api_worker
symptoms: [high_cpu, throttling, latency]
environments: [production, staging]
tags: [cpu, performance, kubernetes, autoscaling]
related_runbooks: [sample-runbook-01, runbook-02-memory-pressure-oom, runbook-03-http-5xx-spike]
```
