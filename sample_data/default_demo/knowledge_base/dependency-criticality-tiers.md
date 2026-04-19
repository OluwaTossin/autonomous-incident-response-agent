# Dependency criticality tiers (sample)

Use during triage to decide **escalate**, **degraded mode**, and **comms** tone.

## Tier 0 — hard dependency

Outage or severe degradation **directly** breaks core customer journeys or settlement.

**Examples:** primary OLTP writer, auth IdP for login, payment capture API, production KMS.

**Expectation:** incident commander, status comms if user-visible, **no** silent “best effort” without approval.

## Tier 1 — soft dependency

Degraded performance causes **partial** impact or **non-critical** paths fail.

**Examples:** recommendations, analytics ingest, non-critical notifications, read replicas (if writer healthy).

**Expectation:** feature flags / circuit breakers; may degrade UX with clear messaging.

## Tier 2 — best effort

Failure should **not** block core flows; background jobs may retry.

**Examples:** marketing webhooks, internal ETL, non-SLA reporting.

**Expectation:** shed load, DLQ, fix in business hours unless cascade risk.

## Triage prompts for the agent

1. Is the failing dependency **Tier 0** for this request path?  
2. Is there a **cached / stale** safe response policy?  
3. Are **retries** amplifying load (storm)? — link `RB-EXT-API-008`, `RB-DB-CONN-004`.

## Related runbooks

- `RB-EXT-API-008` — external API failure  
- `RB-DB-CONN-004` — connection exhaustion and failover storms  
