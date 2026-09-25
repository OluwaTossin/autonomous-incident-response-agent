# Immutable execution intents

V3.21 freezes one exact, human-approved `ActionProposal` into one durable
`ExecutionIntent`. It validates and prepares an allowlisted operation but never executes it.

```text
ActionProposal
  -> human Approval APPROVED
  -> revalidate exact binding and bounded approval age
  -> deterministic connector mapping
  -> create immutable ExecutionIntent
  -> connector validation/preparation
  -> persist
  -> operator inspects
  -> STOP
```

No LLM participates after proposal generation. Rationale, source recommendation, log text,
and other free text are display/audit context and never connector instructions.

## Binding and hashing

The intent carries organization, workspace, incident, triage run, proposal, approval,
proposal/result versions and hashes, approval state version and decision fingerprint,
human approver/time, connector, operation, provider, exact typed target and parameters,
risk, reversibility, policy version, preparation actor/time, and `execute_before`.

The approval fingerprint is a canonical SHA-256 digest of the terminal human decision and
its exact proposal binding. The intent hash canonically covers that fingerprint plus every
execution-defining field. The deadline is included because it limits future authority.
Changing a target, parameter, connector, operation, approval, or deadline produces a
different hash and requires a new proposal, approval, and intent.

Database uniqueness permits exactly one intent per approval. `INSERT ... ON CONFLICT`
makes repeated and concurrent preparation idempotent. A database trigger rejects updates
to execution-defining columns; only lifecycle state/version, update time, and terminal
reason/time may change.

## Eligibility and lifetime

Preparation reloads and locks the approval and proposal, then fails closed unless:

- the approval is `approved`, human-attributed, and binds the exact proposal;
- preparation occurs within 30 minutes of `approved_at`;
- the proposal remains `ready_for_review` and `allowed_for_review`;
- the action is not irreversible;
- its target and typed parameters satisfy an allowlisted connector mapping.

The preparation window and intent lifetime are configurable from one minute through 24
hours; both default to 30 minutes. A prepared intent has an `execute_before` deadline.
Reads persist `invalidated` when that deadline elapses or proposal/approval binding drifts.
Authorized cancellation changes `prepared` to `cancelled` and retains the full record.
Neither terminal state can be resurrected.

## Connector boundary

The connector registry is static application code. V3.21 supports only:

```text
internal / acknowledge_incident / aira
```

It accepts only an authoritative incident target and versioned
`AcknowledgeIncidentParameters`. It returns typed `PreparedOperation` metadata and has no
`execute` method. There is no generic HTTP, shell, script, arbitrary provider API, dynamic
connector import, execution Job, or provider mutation endpoint.

V3.19 does not currently persist operation-specific authoritative AWS remediation target
identity. Consequently, every AWS-resource intent fails with `target_not_authoritative`.
AIRA does not derive an ARN or mutation target from a service name, alarm name, logs, or an
LLM recommendation. Integration readiness/account/region validation becomes relevant only
after a future proposal type can carry authoritative operation-specific identity; V3.21
does not weaken that requirement or call AWS.

## Storage, authorization, and RLS

`execution_intents` uses composite tenant foreign keys to workspace, incident, triage run,
proposal, approval, and optional integration, bounded versioned JSONB parameters, forced
RLS, and database checks for the initial connector/operation/target/parameter allowlist.
The application role remains a non-owner without `BYPASSRLS`.

All roles have `execution_intent.read`. Only Owner and Admin have
`execution_intent.prepare` and `execution_intent.cancel`. External service accounts and
system/workload actors receive no implicit capability; a future workload grant must be
explicit. Browser permission flags only control presentation. FastAPI authorization and
transaction-local PostgreSQL RLS remain authoritative.

## API, BFF, and UI

The hosted API provides only:

```text
POST /v3/.../approvals/{approval}/execution-intent
GET  /v3/.../execution-intents/{intent}
GET  /v3/.../action-proposals/{proposal}/execution-intents
POST /v3/.../execution-intents/{intent}/cancel
```

Preparation accepts an approval identifier and an empty, extra-forbidden body. The browser
cannot submit a connector, target, parameters, or provider request. The server-only BFF
keeps bearer credentials out of browser code and applies session-bound origin/CSRF checks
to preparation and cancellation.

The investigation UI displays approval attribution, connector, operation, exact target,
frozen parameters, risk, reversibility, deadline, state, and intent hash. Its wording is
"Execution intent prepared", "Approved action frozen for controlled execution",
"Connector validation passed", and "Not executed". It contains no Execute, Run, Apply, or
Remediate action.

## Audit and phase boundary

Preparation, rejection, connector validation pass/fail, invalidation, and cancellation are
audited with safe IDs, connector, operation, risk, outcome, and a target hash. Raw targets,
credentials, provider responses, and secrets are excluded. Observer dimensions are limited
to connector, operation, result, and risk.

V3.21 stops at local deterministic preparation. V3.22 may provision infrastructure needed
by already implemented hosted services; it does not activate provider mutation. A future
Version 4 design may consume an unexpired prepared intent, perform fresh drift checks, and
create a distinct execution Job. It must never rewrite the intent or transfer authority
from an older triage run.

Version 2 synchronous triage, CLI, Gradio, action strings, filesystem workspace, FAISS,
JSONL audit, and metrics remain unchanged.
