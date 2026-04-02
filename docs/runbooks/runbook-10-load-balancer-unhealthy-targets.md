# Runbook: Load balancer unhealthy targets (ALB/NLB/ingress)

**Runbook ID:** RB-LB-HEALTH-010  
**Service:** AWS ALB/NLB target groups, GCP/GCP LB backends, Kubernetes **Service** + **Ingress** health paths  
**Environment:** Production  
**Primary owner:** Platform / SRE  
**Supporting:** Application teams (health handler logic, port binding)  
**Severity when triggered:** HIGH–CRITICAL when **healthy host count** cannot satisfy traffic  
**Last updated:** 2026-04-02 — Oluwatosin Jegede

---

## Summary

**Unhealthy targets** mean the load balancer’s **health checks** fail, so traffic is drained from instances/pods. Symptom is often **502/503** at edge while **app logs** may look quiet (traffic never arrives). Goal: distinguish **LB misconfig** vs **app actually unhealthy** vs **network/security** path, and restore **quorum** of healthy targets.

---

## Scope and applicability

**In scope:** Target group **UnHealthyHostCount**, **Draining** targets, Kubernetes readiness failing behind Service.

**Out of scope:** **TLS certificate** errors at client — often **`runbook-07-ssl-tls-certificate-expiry.md`** first.

---

## Symptoms and typical alerts

- Cloud: `UnHealthyHostCount` > 0, `HealthyHostCount` < desired.  
- Users: intermittent **502/504**, “empty” responses, regional impact if single AZ targets fail.  
- K8s: pods **Ready** false while process runs — **readiness probe** vs LB health path **mismatch**.

---

## Preconditions

- [ ] **Health check** definition: path, port, protocol, **thresholds**, **timeout**, **matcher** (HTTP code).  
- [ ] **Security groups / NACLs** — LB → target path allowed?  
- [ ] **Deployment** in progress — intentional drain?

---

## Immediate checks (first 5 minutes)

1. **LB vs app path** — Is check hitting **`/health`** while app only exposes **`/ready`** on different port?  
2. **Recent change** — Target group port, **container port**, **ingress** annotation?  
3. **Target state** — `unused`, `draining`, `initial` — normal rollout or stuck?  
4. **Direct to pod** — From inside cluster: `curl` health URL on **pod IP:port** (bypass LB).  
5. **503 at LB** with **zero** healthy — **outage**; partial — **degraded**.

---

## Deeper diagnosis (15–30 minutes)

| Layer | Checks |
|-------|--------|
| **Application** | Health returns **200** under load; no **auth** required on health path; DB check not **too strict** (avoid full DB for liveness if it causes flapping). |
| **Network** | SG rules for **LB subnets** → **target** SG; Pod security policy; NetworkPolicy. |
| **NLB / TCP** | TLS passthrough vs terminate — health check type must match. |
| **Capacity** | Targets **overloaded** — health check times out (ties to **`runbook-01-high-cpu-usage.md`**). |
| **Sticky sessions** | Bad target pinned — check distribution and **drain** behaviour. |

---

## Likely root causes

1. **Wrong health path/port** after deploy or Helm chart change.  
2. **App regression** — health depends on **failing** dependency.  
3. **Timeout too aggressive** under load.  
4. **Firewall / SG** regression.  
5. **All targets** in same **failure domain** (single AZ).

---

## Recommended remediation (ordered)

1. **Rollback** LB or app change if clearly correlated (approved).  
2. **Fix health handler** — fast **200** for LB; deep checks on **readiness** only if architecture supports it.  
3. **Tune checks** — increase timeout/interval **temporarily** only with ticket and follow-up to fix root slowness.  
4. **Restore network path** — SG/NACL/NetworkPolicy fix with peer review.  
5. **Scale** targets if saturation is root cause.

---

## Escalation criteria

- **Zero** healthy in production target group.  
- **Multi-region** or **multi-service** pattern — possible **platform** incident.  
- **Security** change suspected (accidental deny-all).

---

## Communication and status updates

Report **healthy/total** counts per AZ/region and whether impact is **user-facing**.

---

## Recovery verification

- [ ] All targets **healthy** for **two** full check cycles.  
- [ ] Synthetic **edge** checks green from **external** vantage.  
- [ ] Error rate at **origin** and **edge** normal.

---

## Post-incident

- [ ] **Contract tests** for health path in CI.  
- [ ] Document **separation** of liveness vs readiness vs **deep** checks.  
- [ ] **Multi-AZ** target distribution review.

---

## Evidence to capture

Target group ARN/ID, health check JSON, SG rule screenshots, deployment diff, `curl` timings from inside/outside mesh.

---

## Metadata for RAG / automation

```yaml
runbook_id: RB-LB-HEALTH-010
service: load_balancer_ingress
symptoms: [unhealthy_targets, 502, 503, draining, health_check_failed, target_group_unhealthy]
environments: [production, staging]
tags: [alb, nlb, kubernetes_ingress, health_check, networking]
related_runbooks: [runbook-07-ssl-tls-certificate-expiry, runbook-03-http-5xx-spike, runbook-05-kubernetes-crashloopbackoff]
```
