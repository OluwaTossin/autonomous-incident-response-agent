# Hosted usage accounting and quotas

V3.24 adds operational capacity protection for hosted AIRA. It does not implement billing,
prices, plans, invoices, payment processing, or currency amounts. Version 2 remains outside
this system.

## Usage ledger

`usage_events` is the immutable, tenant-scoped detail ledger. Event names and units are
allowlisted. Each record has organization/workspace scope, type, non-negative integral
quantity, unit, UTC occurrence time, source, durable source reference, optional resource
reference, correlation, and actor attribution. Provider token counts are recorded only when
the existing LangChain callback returns authoritative input/output metadata; AIRA does not
estimate tokens from text length.

Logical work is distinct from retry activity. `TRIAGE_REQUESTED` is keyed by TriageRun,
`ALERT_EVENT_ACCEPTED` by EventBridge event ID, stored document bytes by immutable document
version, and completion/token usage by TriageRun. Job retries and duplicate queue or alarm
deliveries therefore do not increment logical usage again.

`usage_counters` contains atomic bounded aggregates for lifetime and fixed UTC-hour windows.
An event insert and its counter increments share one transaction. The unique tenant, usage
type, source, and source-reference identity makes replay idempotent. Counters cannot be
negative. Raw events remain available for explanation and reconciliation but are not scanned
on every admission request.

## Policy and admission

Effective policy precedence is workspace override, organization policy, then deployment
default. Overrides are versioned rows; defaults are non-secret `AIRA_QUOTA_*` runtime
settings. V3.24 exposes no quota mutation API, so browser users cannot raise limits. A later
operator-only control may manage overrides with audit.

Each limit has a hard limit, warning percentage, deterministic window, and policy version.
At the warning threshold work is admitted and an aggregate warning metric is emitted. A
request whose resulting quantity would exceed the hard limit is rejected. Exactly at the
limit is allowed. Fixed windows start on the UTC hour and return that hour's end as
`reset_at`; resource-count and storage limits have no scheduled reset.

The initial enforced limits are:

| Quota | Semantics |
| --- | --- |
| Triage requests/hour | One logical TriageRun; retries do not count |
| Concurrent triage runs | Pending and running TRIAGE jobs |
| Documents | Non-archived document records |
| Document bytes | Pending expected bytes or verified bytes for retained versions |
| Active AWS integrations | All integration states except disabled |
| Alert events/hour | New deduplicated EventBridge events |
| Concurrent index builds | Index versions in BUILDING state |
| Execution intents/hour | Newly prepared immutable intents |

Race-sensitive checks take a transaction-scoped PostgreSQL advisory lock keyed by tenant
and quota type. The check, durable business records, usage event, and counter update then
commit together. Python locks are never authoritative. Existing in-flight work is not
cancelled when a threshold changes. Archived workspaces retain history and remain blocked
from new work by existing authorization.

Alert intake deduplicates first. A new logical event above the hourly limit is persisted as
policy-ignored and acknowledged, preventing an EventBridge/SQS retry storm; it does not create
an incident or triage job. Duplicate deliveries remain duplicate acknowledgements.

## API and authorization

`GET /v3/organizations/{organization_id}/workspaces/{workspace_id}/usage` returns bounded
effective quota summaries: current, limit, remaining, status, reset time, and policy version.
It never returns raw usage events or money. `usage.read` remains Owner/Admin only. The hosted
Next.js settings page shows the same operational summary through the server-side session/BFF.

Hard admission failures use HTTP 429 and `quota_exceeded`, with quota type, limit, remaining,
and a truthful `Retry-After` only for windowed quotas. Internal policy-state failures fail
closed before expensive new work. Accounting coupled to an admitted creation is atomic;
post-completion accounting is idempotent and does not manufacture provider usage.

Usage events, counters, and policies have composite tenant relationships and forced RLS.
Missing or cross-workspace transaction context sees no rows and cannot mutate another tenant.
CloudWatch usage signals are aggregate platform health only; tenant IDs and entity IDs remain
forbidden metric dimensions.

## Reconciliation and limitations

The repository exposes an idempotent reconciliation operation that compares a known
authoritative PostgreSQL-derived quantity with the lifetime counter and replaces drift under
tenant scope. Routine reconciliation uses PostgreSQL metadata, not broad S3 listings. The
operator procedure is in `runbooks/usage-quotas.md`.

V3.24 does not yet expose raw-event pagination or quota override mutation. Knowledge bundle
byte accounting is deferred because current publication metadata has no authoritative bundle
size. Document deletion/decrement awaits V3.25 retention semantics. Quota policies exist at
organization and workspace scope, while the initial summary endpoint is workspace-scoped.

