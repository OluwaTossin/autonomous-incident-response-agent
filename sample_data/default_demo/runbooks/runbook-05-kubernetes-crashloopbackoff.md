# Runbook: Kubernetes `CrashLoopBackOff` on application workload

**Runbook ID:** RB-K8S-CRASH-005  
**Service:** Kubernetes `Deployment` / `StatefulSet` / `Job` pods (application containers, sidecars)  
**Environment:** Production / staging / dev  
**Primary owner:** Platform / SRE (cluster, manifests, probes) + **application team** (startup code, image)  
**Supporting:** Security / IAM for secret and cloud access issues  
**Severity when triggered:** MEDIUM–CRITICAL (depends on **ready replica** count and **user impact**)  
**Last updated:** 2026-04-02 — Oluwatosin Jegede

---

## Summary

`CrashLoopBackOff` means the container **starts, exits non-zero (or is killed), and Kubernetes restarts it** until backoff applies. It is a **symptom**, not a root cause. Causes include bad image, missing secret, probe mismatch, dependency down at boot, migration failure, **OOM** (see **`runbook-02-memory-pressure-oom.md`**), or command/entrypoint errors.

---

## Scope and applicability

**In scope:** Pod `State: Waiting` / `CrashLoopBackOff`, high `Restart Count`, rollout stuck, readiness never achieved.

**Out of scope:** **ImagePullBackOff** — treat as registry/auth/network (related but distinct triage). **Node NotReady** cluster-wide — infrastructure incident.

---

## Symptoms and typical alerts

- `kubectl get pods` — `CrashLoopBackOff` or `Error`.
- Events: `Back-off restarting failed container`, `OOMKilled`, `failed liveness probe`, `failed readiness probe`.
- Deployments: `ProgressDeadlineExceeded` or desired ≠ ready.

---

## Preconditions

- [ ] `kubectl` / API access to **namespace**; RBAC to **describe** pods and **logs**.  
- [ ] Known **image tag** and **last successful** revision (for rollback).  
- [ ] Change record for recent manifest, secret, or ConfigMap edits.

---

## Customer impact and blast radius (first 5 minutes)

| Situation | Typical impact |
|-----------|----------------|
| Canary pod only failing | May be **intentional** failure detection — confirm rollout strategy. |
| Majority of replicas down | **Outage** or severe degradation — SEV response. |
| Single AZ / node | Possible **topology** issue — cordon/drain patterns. |

---

## Immediate checks (first 5 minutes)

1. **`kubectl describe pod <pod>`** — Last events, probe failures, OOM, volume mount errors.  
2. **Logs:** `kubectl logs <pod> --previous` (last crashed instance) **and** current.  
3. **Correlation** — New `ReplicaSet`? Image digest change? Secret rotation?  
4. **Probe timing** — App slow-start vs too-aggressive `initialDelaySeconds`?  
5. **Exit code** — `137` → OOM; `1` → app error; interpret with logs.

---

## Deeper diagnosis (15–30 minutes)

| Area | What to inspect |
|------|------------------|
| **Image / command** | `args`, `command`, wrong port, missing env. |
| **Secrets / ConfigMaps** | Keys exist, mounted paths, IAM if using external secret operators. |
| **Startup deps** | DB/cache reachable from **pod network**; DNS; TLS to dependencies. |
| **Migrations** | Job or init container failing and blocking main container. |
| **Resources** | OOM vs CPU throttle killing process. |
| **Security context** | `runAsNonRoot`, `readOnlyRootFilesystem` breaking app assumptions. |

Document **ReplicaSet** IDs, **node** name, and **UTC** timestamps in the incident.

---

## Likely root causes

1. **Regressed image** or incompatible config.  
2. **Missing/wrong secret** after rotation.  
3. **Readiness/liveness** too strict or wrong HTTP path/port.  
4. **Dependency** unavailable at boot (ordering).  
5. **OOM** or resource limits.  
6. **Permissions** — file system, cloud API, service account.

---

## Recommended remediation (ordered)

1. **Pause or rollback rollout** to last known good **Revision** (per change policy).  
2. **Fix fast:** restore secret/config; adjust probes **only** with staging proof + MR.  
3. **Scale** stable ReplicaSet if available while fixing forward (temporary).  
4. **Do not** delete pods blindly in a loop — understand exit reason first.  
5. **Forward fix:** corrected image or manifest via CI/CD — avoid manual drift.

---

## Escalation criteria

- **Service down** or SLO breach.  
- **Security** suspicion (unexpected image, tampered secret).  
- **Cluster-wide** pattern (CNI, control plane) — platform major incident.  
- Stuck after **timeboxed** triage (e.g. 30–45 min) — joint app + platform war room.

---

## Communication and status updates

Include **% ready replicas**, **rollout generation**, and whether **rollback** completed. Update stakeholders on **ETA** or **unknown**.

---

## Recovery verification

- [ ] Pods `Running`, **ready** == desired for **two** probe intervals.  
- [ ] No new `CrashLoopBackOff` events.  
- [ ] End-to-end **smoke** or synthetic check green.  
- [ ] Rollout **history** documents what changed.

---

## Post-incident

- [ ] **Startup tests** in CI (smoke container start with test deps).  
- [ ] **Canary + auto-rollback** for this service if not present.  
- [ ] Runbook link from **deployment annotations** or service catalog.

---

## Evidence to capture

`describe pod` output, **previous** logs, events, image ID, diff of ConfigMap/Secret versions (redacted values), timeline of actions.

---

## Structured output example (for AI / automation)

```json
{
  "incident_type": "kubernetes_crashloopbackoff",
  "severity": "HIGH",
  "likely_root_cause": "New ReplicaSet fails startup validation against rotated secret; container exits 1 before readiness",
  "recommended_actions": [
    "kubectl describe pod and logs --previous",
    "Compare current vs previous ReplicaSet env and secret references",
    "Rollback deployment if correlation confirmed",
    "Validate probes and startup dependencies in staging"
  ],
  "escalate": true,
  "confidence": 0.85
}
```

---

## Metadata for RAG / automation

```yaml
runbook_id: RB-K8S-CRASH-005
service: kubernetes_workloads
symptoms: [crashloopbackoff, high_restart_count, probe_failure, oomkilled, rollout_stuck]
environments: [production, staging]
tags: [kubernetes, pods, deployment, probes, rollback]
related_runbooks: [runbook-02-memory-pressure-oom, runbook-06-disk-storage-saturation]
```
