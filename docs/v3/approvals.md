# Human approval workflow

V3.20 adds a durable, workspace-scoped human decision for an exact controlled action
proposal. Approval authorizes a possible future V3.21 execution intent. It does not call a
provider, mutate infrastructure, dispatch an action, or change the proposal into an
execution state.

```text
ActionProposal READY_FOR_REVIEW
  -> approval requested
  -> authorized human reviews exact proposal
  -> approve / reject / expire / cancel
  -> persist decision
  -> STOP
```

## Exact proposal binding

An approval references one `ActionProposal` by ID and stores its proposal schema version,
source-result version and hash, and normalized-action hash. It does not copy or reinterpret
the proposal. At decision time the application locks and reloads both records, verifies the
binding, and rechecks that the proposal is still `ready_for_review`, policy status is
`allowed_for_review`, and reversibility is not irreversible. A changed, superseded,
cancelled, blocked, or otherwise ineligible proposal cancels the pending request and returns
a conflict. A new triage run creates new proposals; approval never migrates to them.

Only structurally valid V3.19 targets can be represented by the domain model. Dynamic
provider authority and current execution policy must be checked again when V3.21 creates an
execution intent. V3.20 does not create that intent.

## Lifecycle and expiry

The lifecycle is deliberately small:

```text
requested -> approved
requested -> rejected
requested -> expired
requested -> cancelled
```

All four destinations are terminal and immutable. Requests use a bounded configurable TTL,
stored as UTC `requested_at` and `expires_at`; the default is 30 minutes and the supported
range is one minute through 24 hours. A decision is valid only when
`decision_time < expires_at`. At exactly `expires_at`, lazy read/decision expiry or the
bounded `expire_due` application operation persists `expired` before returning. V3.21 must
also reject an approval that is not valid for the exact proposal and current target context.

There is at most one active `requested` row per tenant/proposal, enforced by a partial
unique index. Repeated and concurrent requests return the active row. Terminal history is
retained, ordered newest first. The requester or an Admin/Owner may cancel a pending
request; terminal decisions cannot be cancelled.

## Human and authorization policy

Only authenticated human actors may request, approve, reject, or cancel. The application
domain and database constraints both reject service-account, workload, system, worker, and
LLM-derived decision identities.

- Owner, Admin, and Operator have `approval.request`.
- Owner and Admin have `approval.decide`.
- Viewer has neither mutation permission.
- All roles with incident visibility have `approval.read`.
- The requester may never approve or reject their own request, regardless of risk.

This is a strict two-person rule for every V3.20 proposal. Rejection requires a non-empty
reason; approval and cancellation accept an optional reason. Reasons are trimmed and
limited to 1,000 characters and must not contain secrets. Authorization is recalculated
from current memberships for every operation; browser role state is never authoritative.
Recent-authentication and Cognito step-up flows are not implemented. Stronger authentication
freshness remains a V3.25 hardening decision and normal session age must not be described as
step-up authentication.

## Concurrency, persistence, and isolation

The application service is transport-neutral and runs through the hosted incident unit of
work. Decision paths lock the proposal and approval, then persist with a state-version
compare-and-swap. Concurrent approve/approve or approve/reject attempts produce one durable
terminal decision, one audit event, and a conflict for the loser. Decision-versus-expiry
uses the same `decision_time < expires_at` rule.

The `approvals` table has composite organization/workspace/proposal foreign keys, forced
RLS, human actor checks, lifecycle/decision-shape checks, bounded reasons, version checks,
and indexes for history and pending-expiry scans. The runtime role cannot bypass RLS.
Missing, cross-organization, and cross-workspace context fails closed.

Each requested, approved, rejected, expired, or cancelled transition writes an audit event
in the same transaction. Audit metadata contains bounded IDs, state, risk, type, and exact
proposal hashes, but no credentials, raw provider output, or proposal parameter payload.
Observer hooks expose request/decision/expiry/cancellation counts and decision latency using
only outcome, risk, and proposal type as dimensions.

## API, BFF, and UI

Hosted routes provide request, list, detail, approve, reject, and cancel operations beneath
the tenant-scoped V3 API. There is no execute route. Browser calls remain same-origin through
the server-only BFF: the secure session supplies the bearer token, every mutation requires
the V3.13 origin and CSRF checks, FastAPI enforces current RBAC, and PostgreSQL enforces RLS.

The investigation view shows the complete proposal type, target, parameters, risk,
reversibility, policy reason, rationale, requester, expiry, decision attribution, reason,
and retained history. Its language is explicit: "Approval requested", "Approved for future
execution", "Rejected", "Expired", or "Cancelled". It has no Execute control and never
claims that a fix was applied.

## Phase boundaries

V3.21 may consume a still-valid approval to create a separate immutable execution intent,
after revalidating proposal binding, policy, target authority, actor authorization, and
bounded approval age. It validates a deterministic connector mapping but does not execute
it. Provider mutation, execution jobs, retries/outcomes, and rollback remain Version 4
work. See [`execution-intents.md`](execution-intents.md). Autonomous approval and
autonomous remediation remain separate boundaries. Version 2 synchronous triage, CLI,
Gradio, recommended actions, and self-hosted behavior are unchanged.
