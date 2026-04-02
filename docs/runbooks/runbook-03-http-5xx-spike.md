# Runbook: HTTP 5xx error rate spike

**Runbook ID:** RB-HTTP-5XX-003  
**Service:** HTTP/HTTPS APIs behind load balancers, gateways, or ingress  
**Environment:** Production (staging for rehearsal)  
**Primary owner:** Owning service team  
**Supporting:** Platform / SRE, DBAs if datastore correlated  
**Severity when triggered:** Often HIGH–CRITICAL when **rate** and **breadth** exceed SLO  
**Last updated:** 2026-04-02 — Oluwatosin Jegede

---

## Summary

A **5xx spike** means server-side failures increased materially. **5xx is a symptom** — causes include deploy regression, dependency outage, saturation, misconfig, or auth/secret failures. Goal: narrow **layer** (edge vs app vs DB), **scope** (% traffic), and **time correlation** (release, dependency, load).

---

## Scope and applicability

**In scope:** `500`, `502`, `503`, `504` from app or upstream (as reported at edge or service mesh).

**Out of scope:** **4xx** primarily (client/auth) — different triage unless misclassified. Pure **client timeouts** with `200` — check latency SLO runbooks.

---

## Symptoms and typical alerts

- Error-rate SLO burn; `http_requests_total{status=~"5.."}` spike; ALB/NLB `5XXError` metrics.
- Spike in **specific routes** vs global (helps isolate code path).
- Logs: stack traces, `connection refused`, `timeout`, `upstream prematurely closed`.

---

## Preconditions

- [ ] Dashboards: global vs per-route 5xx, p95 latency same window.  
- [ ] Trace ID sampling if available (tie request → backend → DB).  
- [ ] Last successful deploy / config push time.

---

## Immediate checks (first 5 minutes)

1. **Edge vs origin** — 502/504 often **gateway ↔ upstream**; 500 often **app thrown**.  
2. **Single region/AZ** — partial blast radius vs global.  
3. **Deploy** — Did canary or full rollout align with spike start? **Rollback** candidate.  
4. **Dependencies** — DB, cache, queue, external API errors in same minute boundary.  
5. **Saturation** — CPU/memory/thread pool exhaustion presenting as 503/500.

---

## Deeper diagnosis (15–30 minutes)

| Layer | Checks |
|-------|--------|
| **Load balancer / ingress** | Healthy host count, target group draining, TLS errors, idle timeout. |
| **Service mesh** | Upstream cluster health, circuit break, retry storms. |
| **Application** | Exception rate by type; thread pool rejections; GC pauses. |
| **Data tier** | Connection errors, failover events, read replica lag. |
| **External API** | Partner status page, increased latency, auth/quotas. |

---

## Likely root causes

1. Bad **release** (logic, schema, feature flag).  
2. **Dependency** hard or soft failure (timeouts → 5xx).  
3. **Capacity** — overload, queue full, DB max connections.  
4. **Config/secrets** — wrong endpoint, expired internal cert, bad env in new pods only.  
5. **Infrastructure** — AZ impairment, subnet routing, DNS blip.

---

## Recommended remediation (ordered)

1. **Customer impact first:** rollback, scale, or disable **non-critical** features via flag (approved).  
2. **Stabilise dependencies** — failover, scale read path, rate-limit ingress to backend if necessary.  
3. **Fix misconfig** — secrets, service URLs, TLS chain (with change record).  
4. **Post-fix:** verify **canary** and automated rollback for next release.

---

## Escalation criteria

- **SLO burn** or widespread user reports.  
- **Data loss / corruption** suspected from error patterns.  
- **Security** (auth system down, mass 401/500 confusion) — follow sec incident channel.  
- Multi-team **unknown** after timeboxed triage — incident commander.

---

## Communication and status updates

State **customer-visible yes/no**, **affected regions**, **error sample rate** (not raw PII). Frequent updates during SEV.

---

## Recovery verification

- [ ] 5xx rate at baseline for **two** evaluation windows.  
- [ ] Latency and saturation metrics normal.  
- [ ] No elevated errors on **canary** if progressive delivery is used.

---

## Post-incident

- [ ] Add **synthetic checks** for critical routes if gap found.  
- [ ] Improve **SLO alerts** (burn rate) vs static threshold.  
- [ ] Blameless review if SEV-1/2.

---

## Evidence to capture

Time-aligned graphs (edge + app + DB), deployment IDs, representative **redacted** error messages, trace IDs, change tickets.

---

## Metadata for RAG / automation

```yaml
runbook_id: RB-HTTP-5XX-003
service: generic_http_api
symptoms: [5xx_spike, error_rate, bad_gateway, service_unavailable, gateway_timeout]
environments: [production, staging]
tags: [http, errors, slo, load_balancer, ingress]
related_runbooks: [runbook-04-database-connection-exhaustion, runbook-08-external-api-dependency-failure, runbook-10-load-balancer-unhealthy-targets]
```
