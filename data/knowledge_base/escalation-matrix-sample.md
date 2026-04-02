# Escalation matrix (sample)

Synthetic template aligned with [`docs/decisions/problem-definition.md`](../../docs/decisions/problem-definition.md). Replace with your org’s real matrix.

## Severity → response

| Level | Meaning | Notify | Response time target |
|-------|---------|--------|----------------------|
| **SEV-1** | Customer-impacting outage or data risk | Primary + secondary on-call, incident commander | Immediate |
| **SEV-2** | Major degradation, partial outage | Service owner + platform on-call | ≤ 15 min ack |
| **SEV-3** | Minor impact, workaround exists | Service owner (next business hours if safe) | ≤ 1 h ack |
| **SEV-4** | No user impact | Ticket only | Best effort |

## Domain → owner (example org)

| Domain | Primary | Secondary |
|--------|---------|-----------|
| Payments / ledger | `team-payments` | `team-platform` |
| Data / RDS | `team-data` | `team-platform` |
| Edge / TLS / ALB | `team-platform` | `team-security` |
| Kubernetes / ECS | `team-platform` | `team-sre` |
| Identity / auth | `team-security` | `team-platform` |

## When to escalate out of band

- Suspected **security incident** or **fraud** spike  
- **Compliance** or **legal** hold on communication  
- **Vendor** Tier-0 outage beyond internal mitigation  

## Related

- Runbooks: `docs/runbooks/`  
- Incidents: `data/incidents/`
