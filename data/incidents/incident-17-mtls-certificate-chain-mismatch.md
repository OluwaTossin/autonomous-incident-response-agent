# INC-017 — Service mesh mTLS: missing intermediate after private CA rotation

| Field | Value |
|-------|--------|
| **Severity** | SEV-2 |
| **Environment** | production |
| **Window** | `2026-03-05T08:00Z` → `2026-03-05T09:40Z` |
| **Status** | resolved |

## Executive summary

Private **CA** rotation issued new leaf certs but automation deployed **only** the leaf to sidecars, omitting the **new intermediate**. Peers with strict chain validation rejected handshakes → **503** on east-west traffic between `billing` and `ledger`.

## Impact

- **Internal** only (not public internet); **~12%** of ledger calls failed for **100 minutes**.
- Batch settlement delayed; **no** customer-visible card errors (queued).

## Timeline (UTC)

| Time | Event |
|------|--------|
| 08:00 | Mesh 503 between specific service pairs |
| 08:25 | `openssl verify` showed **unable to get local issuer** |
| 08:50 | Redeployed **full chain** bundle via secret operator |
| 09:40 | Mesh checks green |

## Detection

Service mesh metrics (TLS handshake failures) + spike in `upstream_reset`.

## Root cause

**Incomplete chain** in cert bundle; staging used **full trust store** that masked issue.

## Resolution

Full chain in Secret; CI **lint** `openssl verify -CAfile` against minimal trust.

## Runbooks

- **Primary:** `RB-TLS-CERT-007` — `data/runbooks/runbook-07-ssl-tls-certificate-expiry.md`
- **Related:** `RB-HTTP-5XX-003`, `RB-EXT-API-008`

```json
{
  "incident_id": "INC-017",
  "severity": "HIGH",
  "primary_runbook_ids": ["RB-TLS-CERT-007"],
  "related_runbook_ids": ["RB-HTTP-5XX-003", "RB-EXT-API-008"],
  "services_affected": ["billing", "ledger", "service-mesh"],
  "symptoms": ["mtls_failure", "503_internal", "chain_incomplete"],
  "root_cause_category": "misconfiguration",
  "expected_triage_severity": "HIGH",
  "expected_escalate": true
}
```
