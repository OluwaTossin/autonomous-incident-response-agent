# Runbook: SSL/TLS certificate expiry or handshake failure

**Runbook ID:** RB-TLS-CERT-007  
**Service:** Public websites, APIs, internal mTLS, load balancers (ALB/NLB), ingress controllers, CDN edge certs  
**Environment:** Production  
**Primary owner:** Platform / SRE + **security / PKI** where applicable  
**Supporting:** Application teams for in-app TLS or misconfigured SNI  
**Severity when triggered:** CRITICAL at **expiry**; HIGH for **misconfig** before expiry  
**Last updated:** 2026-04-02 — Oluwatosin Jegede

---

## Summary

Certificates that **expire** or **fail validation** break browsers, mobile apps, and service-to-service TLS. Goal: **restore trusted chain** quickly (renew/replace), identify **automation gap** (ACME failure, manual process), and document **preventive** monitoring (30/14/7-day alerts).

---

## Scope and applicability

**In scope:** X.509 server certs, **intermediate** chain issues, **SNI** mismatch, **internal CA** expiry, **Kubernetes** `tls` secrets used by ingress.

**Out of scope:** **Client cert** auth policies — use identity/IAM runbooks unless symptom is server-side only.

---

## Symptoms and typical alerts

- Monitoring: `CertificateExpiresInNDays`, synthetic TLS check failure.  
- Users: browser **NET::ERR_CERT_*** , app TLS errors, `curl` handshake failure.  
- Load balancer: **default cert** served (wrong hostname) — SNI or listener misconfig.

---

## Preconditions

- [ ] **Hostname(s)** and **environment** affected (prod vs staging).  
- [ ] **Cert source:** ACM, Let’s Encrypt, internal PKI, HashiCorp Vault, manual import.  
- [ ] **Chain of custody** — who can approve issuance and deploy.

---

## Immediate checks (first 5 minutes)

1. **Expiry vs chain** — `openssl s_client -connect host:443 -servername host` (or internal equivalent) — note **Not After** and **verify return code**.  
2. **Scope** — Single hostname vs wildcard vs **entire** ingress mispointed.  
3. **Recent change** — Listener update, CDN cert swap, secret rotation job failed?  
4. **ACME / automation** — Rate limit hit, DNS-01 challenge failure, stale `Order`?

---

## Deeper diagnosis (15–30 minutes)

| Area | Checks |
|------|--------|
| **Public edge** | CDN cert vs origin cert; which layer terminates TLS? |
| **Load balancer** | Correct cert ARN attached; cipher policy vs legacy clients. |
| **Kubernetes** | `tls.crt` / `tls.key` secret bytes; ingress `tls` section host match. |
| **mTLS internal** | Both sides trust same CA; intermediate not dropped. |
| **Clock skew** | NTP on nodes (rare but breaks validation). |

---

## Likely root causes

1. **Manual cert** renewal missed.  
2. **Automation failure** (ACME, Vault lease not renewed).  
3. **Wrong secret** deployed or **namespace** mismatch.  
4. **Incomplete chain** (missing intermediate).  
5. **Hostname/SNI** change without new cert.

---

## Recommended remediation (ordered)

1. **Issue or fetch** renewed cert via approved PKI path; **test in staging** if time allows.  
2. **Deploy** to LB/ingress/secret; **validate** from external synthetics and internal mesh.  
3. **Purge CDN** cache only if cert is served at edge layer (follow CDN docs).  
4. **Lower TTL** temporarily during cutover if rollback needed (policy-dependent).  
5. **Fix automation:** renew **before** 30 days; alert on job failure.

---

## Escalation criteria

- **Production** customer-facing **down** or **PII** exposure risk from **wrong** cert.  
- **Compliance** breach (e.g. expired cert in regulated flow) — notify per policy.  
- **Cannot issue** within SLA — escalate PKI / security + leadership.

---

## Communication and status updates

Certificate incidents are **highly visible** — prepared **status page** text if customer-facing; avoid sharing private keys in chat (use secure channels).

---

## Recovery verification

- [ ] External synthetic: **valid chain**, correct **SANs**, expiry **> N days**.  
- [ ] Key apps (mobile, partners) succeed — spot-check **non-Chrome** if relevant.  
- [ ] Monitoring green for **all** monitored hostnames in scope.

---

## Post-incident

- [ ] **Automate** renewal with auditable alerts.  
- [ ] Inventory **all** certs (tag owner, expiry).  
- [ ] Blameless review if expiry was preventable.

---

## Evidence to capture

Cert serial (not private key), issuer, SAN list, deployment ticket, `openssl` verify output (redacted), timeline.

---

## Metadata for RAG / automation

```yaml
runbook_id: RB-TLS-CERT-007
service: tls_edge_ingress
symptoms: [cert_expired, tls_handshake_failure, wrong_cert, sni_mismatch, acme_failure]
environments: [production, staging]
tags: [tls, ssl, certificates, acm, letsencrypt, ingress]
related_runbooks: [runbook-10-load-balancer-unhealthy-targets, runbook-03-http-5xx-spike]
```
