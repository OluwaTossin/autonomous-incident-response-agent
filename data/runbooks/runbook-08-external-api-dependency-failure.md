# Runbook: External API / third-party dependency failure

**Runbook ID:** RB-EXT-API-008  
**Service:** Any internal service calling **partner, SaaS, or public HTTP APIs** (payments, maps, auth IdP, webhooks)  
**Environment:** Production  
**Primary owner:** Owning integration team  
**Supporting:** SRE (timeouts, retries, circuit breakers), **vendor management** for contractual SLAs  
**Severity when triggered:** MEDIUM–CRITICAL depending on **critical path** and **degradation mode**  
**Last updated:** 2026-04-02 — Oluwatosin Jegede

---

## Summary

**External dependency failure** includes vendor **outages**, **latency**, **rate limits**, **auth/contract** changes, and **DNS/TLS** to third parties. Goal: confirm **our** side vs **theirs**, protect **our** platform (circuit break, shed load), and communicate **impact** and **ETA** using vendor status and traces.

---

## Scope and applicability

**In scope:** Outbound HTTPS/gRPC to third parties; webhook **delivery** failures if **we** are client to their endpoint.

**Out of scope:** **Our** API broken for clients — see **`runbook-03-http-5xx-spike.md`**. **Database** internal — other runbooks.

---

## Symptoms and typical alerts

- Elevated **timeout** or **5xx** from `http_client_requests` to specific host.  
- **429** / quota exceeded; **401/403** after key rotation.  
- Business KPI drop (e.g. payment capture) correlated with vendor window.

---

## Preconditions

- [ ] **Dependency register:** owner, **criticality** (tier 0–3), **fallback** behaviour.  
- [ ] **Secrets** location for API keys; **IP allowlist** docs if any.  
- [ ] Vendor **status page** URL and **support** contract level.

---

## Immediate checks (first 5 minutes)

1. **Vendor status** — Confirmed incident?  
2. **Our error taxonomy** — Timeout vs connect vs TLS vs HTTP 5xx vs 401.  
3. **Time correlation** — Our deploy changed **timeout**, **URL**, or **key**?  
4. **Blast radius** — Single region integration vs global config.  
5. **Retry behaviour** — Are we **amplifying** outage (retry storm)? Check **`Retry-After`**.

---

## Deeper diagnosis (15–30 minutes)

| Check | Purpose |
|-------|---------|
| **Synthetic** `curl` from jump host or diagnostic pod | Rule out app bug vs network egress. |
| **mTLS / IP allowlist** | Partner-side block after our NAT change. |
| **Rate limits** | Quota, burst, wrong **environment** key (test vs prod). |
| **Payload contract** | Versioned API deprecation — 400 with body hints. |
| **DNS** | Resolver, TTL, split-horizon mistakes. |

Capture **trace IDs** and **redacted** request metadata for vendor ticket.

---

## Likely root causes

1. **Vendor incident** or brownout.  
2. **Expired or rotated** API key / OAuth client secret on **our** side.  
3. **Network** egress, proxy, or firewall change.  
4. **Overload** — we exceeded **SLA** quota.  
5. **Breaking API** version — insufficient contract testing.

---

## Recommended remediation (ordered)

1. **Protect platform:** enable **circuit breaker**, **bulkhead**, or **cached degraded mode** if designed (do not invent unsafe fallbacks).  
2. **Reduce load:** backoff retries, **disable non-critical** jobs calling vendor (approved).  
3. **Fix credentials** or config via standard secret rotation — verify in **staging** first if possible.  
4. **Coordinate with vendor** — support ticket with timestamps, region, error samples.  
5. **Comms:** internal status; external only per **comms policy**.

---

## Escalation criteria

- **Tier-0** dependency down with **no** degraded mode — executive + vendor escalation.  
- **Financial** or **regulatory** exposure (payments, identity).  
- **Security** concern (suspected breach vs outage) — security channel.

---

## Communication and status updates

Distinguish **“vendor down”** vs **“our misconfig”** once known; update **every 15–30 min** during long vendor incidents.

---

## Recovery verification

- [ ] Error rate and latency to vendor **at baseline**.  
- [ ] **Synthetic** check from two networks (e.g. prod + DR path if applicable).  
- [ ] Backlog of **retries** drained without overload.

---

## Post-incident

- [ ] **Runbooks** for each tier-0 vendor with **fallback** design.  
- [ ] **Timeout and retry** standards in service template.  
- [ ] Quarterly **drill** with expired key simulation in non-prod.

---

## Evidence to capture

UTC windows, HTTP status distribution, vendor ticket ID, config diff (no secrets), architecture diagram snippet.

---

## Metadata for RAG / automation

```yaml
runbook_id: RB-EXT-API-008
service: outbound_integrations
symptoms: [vendor_timeout, 429, 503_upstream, auth_failure_partner, webhook_failure]
environments: [production]
tags: [integrations, third_party, http_client, circuit_breaker, rate_limit]
related_runbooks: [runbook-03-http-5xx-spike, runbook-04-database-connection-exhaustion]
```
