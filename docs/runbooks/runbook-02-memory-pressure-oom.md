# Runbook: Memory pressure and OOM (containers / JVM / Node)

**Runbook ID:** RB-MEM-OOM-002  
**Service:** Containerised or VM workloads with bounded memory (JVM, Node, Go, Python, etc.)  
**Environment:** Production / staging  
**Primary owner:** Owning service team  
**Supporting:** Platform / SRE  
**Severity when triggered:** MEDIUM–CRITICAL (OOM kills often cause **immediate** traffic loss on affected replicas)  
**Last updated:** 2026-04-02 — Oluwatosin Jegede

---

## Summary

**Memory pressure** leads to GC thrashing, slow responses, or **OOMKilled** containers. In Kubernetes, OOM is a **hard stop** — pods restart and may enter `CrashLoopBackOff` (see **`runbook-05-kubernetes-crashloopbackoff.md`**). Goal: confirm leak vs spike vs mis-sized limits, restore capacity, and prevent recurrence.

---

## Scope and applicability

**In scope:** Process RSS, container `memory.working_set`, JVM heap, Node heap, cgroup OOM, `Exit Code 137`.

**Out of scope:** Host-level RAM failure (hardware) — page infrastructure / cloud support with node evidence.

---

## Symptoms and typical alerts

- Alerts: `MemoryUtilizationHigh`, `OOMKilled`, `ContainerRestarting`, JVM `HeapUsed` high.
- `kubectl describe pod`: `Reason: OOMKilled`, `Last State: Terminated`, exit **137**.
- Logs: `OutOfMemoryError`, `Java heap space`, `Allocation failed`, RSS climbing monotonically over hours (leak pattern).

---

## Preconditions

- [ ] Access to pod/VM metrics (memory working set, RSS, heap if exposed).  
- [ ] Memory **requests and limits** for the workload (K8s or equivalent).  
- [ ] Recent deploy or dependency change timeline.

---

## Immediate checks (first 5 minutes)

1. **OOM vs pressure** — Confirmed kill (137) vs only high utilisation?  
2. **One replica vs all** — Leak often starts on subset; bad config may hit all.  
3. **Deploy correlation** — New image, heap flag, cache size change?  
4. **Traffic spike** — Large payloads, export jobs, or deserialization attacks.  
5. **Do not** only raise limits without hypothesis — captures evidence first.

---

## Deeper diagnosis (15–30 minutes)

| Area | What to inspect |
|------|------------------|
| **Limits vs usage** | Working set approaching limit? Brief spike or sustained climb? |
| **JVM** | Heap dump (off-peak if possible), metaspace, GC logs, `-Xmx` vs container limit (avoid **heap > cgroup**). |
| **Node** | Node memory pressure evictions — distinguish pod OOM from node OOM. |
| **Application** | Caches without bounds, unclosed streams, large in-memory batches. |
| **Sidecars** | Combined limit too low for app + envoy/agent. |

---

## Likely root causes

1. **Memory leak** in application or library version.  
2. **Undersized limit** for legitimate peak (fix capacity, not “ignore”).  
3. **Heap/container mismatch** (JVM thinks it has more RAM than cgroup).  
4. **Traffic or message size** anomaly (large JSON, bulk import).  
5. **Node overcommit** or noisy neighbour (less common on dedicated node pools).

---

## Recommended remediation (ordered)

1. **Restore availability:** scale replicas (short-term relief if leak is slow), **roll back** bad release if correlated.  
2. **Bounded mitigations:** restart **only** with understanding (may hide leak); prefer single canary + heap capture.  
3. **Adjust limits** only with sizing rationale and cost/scheduler review — pair with **heap/GC** tuning for JVM.  
4. **Engineering ticket:** leak reproduction, dump analysis, add memory guardrails in code.

---

## Escalation criteria

- **Repeated OOM** across majority of replicas or SLO breach.  
- Suspected **security** (memory-based DoS, huge payloads).  
- Cannot obtain dumps or metrics within **timebox** — escalate to platform + app team jointly.

---

## Communication and status updates

OOMs are often **user-visible**; use incident channel, note restart count and **customer impact** if known.

---

## Recovery verification

- [ ] No OOM events for **two** full alert cycles.  
- [ ] Memory utilisation stable under expected peak profile.  
- [ ] Ready replicas == desired; no crash loop.

---

## Post-incident

- [ ] JVM: validate **container-aware** heap defaults in CI/CD.  
- [ ] Add **growth** alerts (derivative of memory) for early leak detection.  
- [ ] Postmortem if customer-impacting.

---

## Evidence to capture

`describe pod` events, memory graphs, heap/GC logs (redacted), image tag, before/after limit values, HPA behaviour.

---

## Metadata for RAG / automation

```yaml
runbook_id: RB-MEM-OOM-002
service: generic_containerized
symptoms: [oom, memory_high, exit_137, crashloop, gc_pressure]
environments: [production, staging]
tags: [memory, jvm, kubernetes, oomkilled]
related_runbooks: [runbook-05-kubernetes-crashloopbackoff, runbook-01-high-cpu-usage]
```
