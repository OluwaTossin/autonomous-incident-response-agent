# INC-007 — Public API TLS cert expired (manual renewal missed)

| Field | Value |
|-------|--------|
| **Severity** | SEV-1 |
| **Environment** | production |
| **Window** | `2026-01-10T00:02Z` → `2026-01-10T01:14Z` |
| **Status** | resolved |

## Executive summary

The **ingress** TLS certificate for `api.example.com` **expired** at midnight UTC. ACME automation had been **disabled** during a migration and not re-enabled. Browsers and mobile apps failed handshake; synthetics went red immediately.

## Impact

- **100%** API traffic failure for hostname until new cert deployed.
- ~72 minutes to full recovery including DNS/ CDN cache considerations.

## Timeline (UTC)

| Time | Event |
|------|--------|
| 00:02 | Global synthetic TLS failure |
| 00:08 | Confirmed `Not After` in past via `openssl s_client` |
| 00:25 | Emergency issuance via ACM; attached to ALB |
| 01:14 | All probes green after edge propagation |

## Detection

External synthetics (first); customer reports (second).

## Root cause

**Process failure:** migration checklist item “re-enable cert-manager” never closed; **no** 30-day expiry alert on that hostname.

## Resolution

New cert; re-enabled automation; imported all public names into **central cert inventory** with tiered alerts.

## Runbooks

- **Primary:** `RB-TLS-CERT-007` — `data/runbooks/runbook-07-ssl-tls-certificate-expiry.md`
- **Related:** `RB-LB-HEALTH-010`, `RB-HTTP-5XX-003`

```json
{
  "incident_id": "INC-007",
  "severity": "CRITICAL",
  "primary_runbook_ids": ["RB-TLS-CERT-007"],
  "related_runbook_ids": ["RB-LB-HEALTH-010", "RB-HTTP-5XX-003"],
  "services_affected": ["public-api-edge"],
  "symptoms": ["tls_expired", "handshake_failure"],
  "root_cause_category": "process_failure",
  "expected_triage_severity": "CRITICAL",
  "expected_escalate": true
}
```
