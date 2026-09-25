# Controlled action proposals

V3.19 turns completed hosted triage recommendations into durable, typed, policy-evaluated
`ActionProposal` records. It does not approve or execute them.

```text
completed successful TriageRun
  -> normalize persisted recommended actions
  -> validate typed parameters and explicit target identity
  -> classify risk and reversibility deterministically
  -> evaluate deterministic proposal policy
  -> persist ActionProposal and audit event
  -> operator views proposal
  -> STOP
```

The LLM may suggest an action. Its text cannot select policy status, risk, reversibility,
authorization, approval, or execution. Proposal generation does not call the LLM again.

## Proposal contract

Every proposal is scoped to one organization, workspace, incident, and successful
`TriageRun`. It records:

- an allowlisted proposal type and versioned type-specific parameters;
- explicit target type, identifier, provider, and provenance;
- optional AWS integration/account/region authority for trusted AWS resource targets;
- bounded summary and rationale;
- deterministic risk, reversibility, policy result, and machine-readable policy reason;
- lifecycle state, creating actor, timestamps, proposal schema version;
- source triage-result version/hash and normalized-action hash.

The initial types are `acknowledge_incident`, `manual_investigation`,
`restart_workload`, `scale_workload`, and `rollback_deployment`. There is no generic shell,
script, command, or AWS API-call type. Unknown recommendations become manual investigation.
Command-like recommendations are blocked and their executable-looking source text is not
persisted or returned to the browser.

Parameter schema version 1 uses a distinct model for each type. Scale parameters are bounded
and may contain a desired count or bounded direction/delta. Rollback may contain a bounded
target revision. Missing mutation parameters never become executable defaults.

## Targets and policy

Incident identity is authoritative for incident proposals. A service name carried by an
incident can label a candidate, but it is not proof of a provider resource and therefore
remains manual-only. A future AWS-resource target is valid only when it carries persisted
V3.17/V3.18 integration provenance and matches the same workspace integration, AWS account,
and configured region. ARN syntax alone is never ownership proof.

Risk and reversibility are fixed by application policy. Authoritative production metadata
may raise risk; AIRA does not infer environment from resource names. The current policy
returns only:

- `allowed_for_review`: a typed, complete, trusted proposal may be shown for later review;
- `manual_only`: useful guidance lacks a safely actionable target or remains human work;
- `blocked`: the recommendation or target violates a deterministic rule.

Reasons include `ready_for_review`, `manual_guidance`, `unsafe_recommendation`,
`unknown_target`, `untrusted_target`, `cross_tenant_target`, `cross_account_target`,
`region_not_allowed`, `integration_not_ready`, `irreversible`, and
`parameter_out_of_bounds`. No policy result grants approval.

## Persistence, idempotency, and history

Proposal generation runs after the TriageRun and Job success transaction commits. It uses a
separate short PostgreSQL transaction and no provider call. A generation failure is observed
but cannot roll back the completed triage result.

Database uniqueness covers workspace, TriageRun, source-result hash, and normalized-action
hash. Repeated or concurrent generation returns the same logical proposal. A new TriageRun
gets a distinct proposal set; older proposals are retained. V3.19 does not automatically
supersede old proposals because it has no approval or execution semantics to invalidate.

`action_proposals` uses composite tenant foreign keys and forced RLS. Its runtime role remains
a non-owner without `BYPASSRLS`. AWS target references use a tenant-consistent integration
foreign key. Missing, cross-organization, and cross-workspace tenant context cannot read or
write proposals.

Creation is an internal worker/service operation using `action.propose`; there is no browser
POST endpoint for a proposal payload. `action.read` controls the read-only list/detail routes,
so every role that can inspect an incident can inspect its proposals. The browser cannot use
the permission label to forge a proposal.

## API, UI, audit, and metrics

The hosted API provides read-only routes:

```text
GET /v3/organizations/{organization}/workspaces/{workspace}/incidents/{incident}/action-proposals
GET /v3/organizations/{organization}/workspaces/{workspace}/triage-runs/{run}/action-proposals
GET /v3/organizations/{organization}/workspaces/{workspace}/action-proposals/{proposal}
```

Responses omit raw command-like recommendations. The investigation UI says "Proposed
action", "Requires review", "Manual only", or "Blocked by policy" and explicitly states
that no action has executed. V3.20 adds human approval controls only for eligible proposals;
it still has no Execute control. See [`approvals.md`](approvals.md).

Creation, blocked, and manual-only outcomes write attributable PostgreSQL audit events with
safe IDs, type, risk, policy, target type, and a target-identifier hash. They exclude
credentials, command text, secrets, raw context, and large parameters. Observer hooks emit
created, blocked, manual, and policy-evaluation signals using only proposal type, risk, and
policy result as bounded dimensions.

## Phase boundaries

- V3.20 provides approval requests, human decisions, expiry, cancellation, exact proposal
  binding, and approval UI without execution.
- V3.21 owns connector execution, immutable execution intent, retries, and outcomes.
- Version 4 owns any separately designed autonomous-remediation capability.

V3.19 calls no AWS mutation API, Kubernetes API, shell, Terraform, deployment API, GitHub
write API, or connector. Version 2 retains its original `recommended_actions` strings and
self-hosted execution paths; it does not depend on PostgreSQL action proposals.
