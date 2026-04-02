# INC-015 — CoreDNS overload: OIDC token fetch failures

| Field | Value |
|-------|--------|
| **Severity** | SEV-1 |
| **Environment** | production |
| **Window** | `2026-01-18T14:20Z` → `2026-01-18T15:45Z` |
| **Status** | resolved |

## Executive summary

A **buggy** DaemonSet upgrade generated excessive **DNS queries** (thundering herd on SRV lookups). **CoreDNS** pods saturated; **NXDOMAIN** latency and **timeouts** rose. Services calling **OIDC** issuer over DNS intermittently failed token refresh → **401** storms on APIs.

## Impact

- **~20 minutes** of elevated auth failures; partial **global** API degradation.
- Misleading initial lead: “IdP outage” — IdP was healthy.

## Timeline (UTC)

| Time | Event |
|------|--------|
| 14:20 | Spike in 401 + `token refresh failed` |
| 14:35 | CoreDNS metrics: high **drops** / latency |
| 14:50 | Identified DaemonSet release; rolled back |
| 15:45 | DNS latency normal; auth errors cleared |

## Detection

401 rate + mesh egress errors; DNS dashboards lagged — improved after incident.

## Root cause

**Client misbehaviour** overwhelming cluster DNS; **no** rate limit on app side; small CoreDNS replica count.

## Resolution

Rollback DaemonSet; scaled CoreDNS; added **NodeLocal DNSCache** on roadmap; reduced OIDC refresh **churn** in SDK config.

## Runbooks

- **Primary:** `RB-EXT-API-008` — `docs/runbooks/runbook-08-external-api-dependency-failure.md` *(dependency/auth over network)*  
- **Related:** `RB-HTTP-5XX-003`, `RB-GEN-HIGH-CPU-001` (CoreDNS CPU)

> **Note:** Add a dedicated **cluster DNS** runbook when you formalise platform SRE docs.

```json
{
  "incident_id": "INC-015",
  "severity": "CRITICAL",
  "primary_runbook_ids": ["RB-EXT-API-008"],
  "related_runbook_ids": ["RB-HTTP-5XX-003", "RB-GEN-HIGH-CPU-001"],
  "services_affected": ["coredns", "multiple-services"],
  "symptoms": ["401", "dns_timeout", "oidc_failure"],
  "root_cause_category": "platform",
  "expected_triage_severity": "CRITICAL",
  "expected_escalate": true
}
```
