# Runbook: Queue backlog, worker lag, and async processing delay

**Runbook ID:** RB-QUEUE-LAG-009  
**Service:** Message queues (SQS, RabbitMQ, Kafka consumer groups), Celery/Bull workers, async job systems  
**Environment:** Production  
**Primary owner:** Owning service / data pipeline team  
**Supporting:** Platform / SRE (broker capacity, networking), DBAs if **outbox** or DB-backed queues  
**Severity when triggered:** MEDIUM–CRITICAL when **age of oldest message** or **SLA for job completion** is breached  
**Last updated:** 2026-04-02 — Oluwatosin Jegede

---

## Summary

**Backlog** means producers enqueue faster than consumers drain, or consumers **stall** (poison messages, slow handlers, downstream locks). Goal: restore **steady-state throughput**, identify **bottleneck** (workers vs broker vs dependency), and avoid **unbounded growth** that risks data loss or disk fill on brokers.

---

## Scope and applicability

**In scope:** Queue **depth**, **consumer lag**, **processing latency** percentiles, DLQ growth.

**Out of scope:** **Synchronous** HTTP latency only — see latency/5xx runbooks unless the same root cause.

---

## Symptoms and typical alerts

- Metrics: `ApproximateAgeOfOldestMessage` (SQS), **lag** per consumer group (Kafka), **ready** jobs (Redis/Rabbit).
- **DLQ** depth increasing — poison or repeated failures.
- User-visible: **delayed** notifications, stale search indices, **stuck** workflows.

---

## Preconditions

- [ ] **Queue names** / topics, **environment**, and **expected baseline** depth (business hours patterns).  
- [ ] **Worker deployment** identity (image, replicas, autoscaling policy).  
- [ ] **Idempotency** and **ordering** requirements — affects replay strategy.

---

## Immediate checks (first 5 minutes)

1. **Producer spike** — Legitimate traffic vs buggy loop **republishing**?  
2. **Consumer health** — Replica count, **OOM/restarts**, **CPU throttle**?  
3. **Broker health** — Broker CPU/disk, partition leadership, **throttling** (managed services).  
4. **Downstream** — Handlers blocked on **DB**, **external API**, or **lock**?  
5. **Feature deploy** — Slower handler or new **batch size**?

---

## Deeper diagnosis (15–30 minutes)

| Area | Investigation |
|------|----------------|
| **Workers** | Per-pod processing rate, concurrency settings, thread pool saturation. |
| **Message profile** | Average size, sudden **large** payloads, bad serialization. |
| **Poison messages** | Same message ID failing; DLQ sample stack traces (redacted). |
| **Kafka-specific** | Consumer group **rebalance** storm, `max.poll.interval`, partition skew. |
| **Ordering** | Single hot partition / key causing serial bottleneck. |

---

## Likely root causes

1. **Insufficient workers** or autoscaler **max** too low.  
2. **Slow handler** — regression or dependency latency.  
3. **Broker capacity** or **network** limits.  
4. **Poison / bad schema** messages blocking **ordered** processing.  
5. **Database** contention — see **`runbook-04-database-connection-exhaustion.md`**.

---

## Recommended remediation (ordered)

1. **Scale workers** horizontally within cost/policy; raise **ceiling** temporarily if burst is known good.  
2. **Pause or shed** **non-critical** producers or job types (feature flag) — documented approval.  
3. **Replay** from DLQ **only** after fixing root cause; use **batch** replay with rate limits.  
4. **Fix handler** — timeout, circuit break to vendor, optimise query.  
5. **Broker ops** — partition rebalance, storage expansion (with data team).

---

## Escalation criteria

- **SLA** for job type breached (e.g. fraud, billing).  
- **Broker** unstable or **data loss** risk — page data platform **immediately**.  
- **Unknown** consumer stall after timebox — war room with app + data + SRE.

---

## Communication and status updates

Report **oldest message age**, **depth trend** (growing vs flat), and **customer-visible** delays.

---

## Recovery verification

- [ ] Depth and lag **trending down** to normal band for time-of-day.  
- [ ] **DLQ** not growing; poison path identified or quarantined.  
- [ ] Worker utilisation stable without constant **rebalance** or **crash**.

---

## Post-incident

- [ ] **Autoscale** on **lag** or **age**, not only CPU.  
- [ ] **Schema validation** at enqueue time to reduce poison messages.  
- [ ] Load test **peak enqueue** with **consumer** headroom.

---

## Structured output example (for AI / automation)

```json
{
  "incident_type": "queue_backlog",
  "severity": "HIGH",
  "likely_root_cause": "Worker pool saturated after deploy increased per-job DB time; lag compounding",
  "recommended_actions": [
    "Scale worker replicas and verify autoscaler max",
    "Compare handler latency and DB metrics to deploy time",
    "Temporarily reduce non-critical enqueue rate if approved",
    "Inspect DLQ for poison messages"
  ],
  "escalate": true,
  "confidence": 0.82
}
```

---

## Metadata for RAG / automation

```yaml
runbook_id: RB-QUEUE-LAG-009
service: async_queues_workers
symptoms: [queue_depth, consumer_lag, oldest_message_age, dlq_growth, delayed_jobs]
environments: [production, staging]
tags: [sqs, kafka, rabbitmq, celery, workers, async]
related_runbooks: [runbook-04-database-connection-exhaustion, runbook-08-external-api-dependency-failure]
```
