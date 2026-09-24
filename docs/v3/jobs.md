# Version 3 Durable Jobs

V3.10 defines the hosted asynchronous work contract independently of any queue. PostgreSQL
job state is authoritative. The V3.11 SQS integration will be a delivery mechanism only: a
message may prompt a worker to inspect a job, but it cannot establish tenant scope, ownership,
attempt state, or completion.

## Job Types And Payloads

Job kinds are an enum, not executable strings. V3.10 proves the model with the existing
`index_build` kind and payload schema 1 containing a `knowledge_index_version_id`. Tenant
identity comes from authorized context and persisted scope, not payload metadata. Payloads are
compact JSON metadata with a canonical SHA-256 hash. They contain resource identifiers, never
document bodies, credentials, presigned URLs, queue receipt handles, or arbitrary code. Future
job kinds must add explicit schemas before use.

## State Machine

```text
PENDING --claim--> RUNNING --complete--> SUCCEEDED
   |                  |  |
   |                  |  +--permanent/exhausted failure--> FAILED
   |                  +-----retryable failure-------------> PENDING
   +--cancel----------------------------------------------> CANCELLED
```

`PENDING` plus `available_at` represents initial work and retry delay; there is no
queue-specific state. Terminal jobs are immutable. Running cancellation sets
`cancellation_requested_at` and remains `RUNNING`; V3.11 workers must check it at safe
checkpoints and acknowledge it. AIRA does not claim forced interruption of active work.

## Idempotency

The unique key is `(organization_id, workspace_id, kind, idempotency_key)`. Creation uses a
database conflict path. Reuse with an equivalent canonical payload returns the existing job;
reuse with a different payload hash fails. Retries remain attempts on the same job and
increment `dispatch_generation` rather than creating replacement jobs.

## Claims, Leases, And Recovery

Claiming locks the row, verifies `PENDING`, `available_at`, and remaining attempts, then records
a generated claim token, worker label, lease expiry, and incremented attempt. Completion,
failure, and cancellation acknowledgement re-lock the row and validate the current token and
unexpired lease. A stale worker cannot commit after recovery or a new claim.

Recovery selects expired rows with `FOR UPDATE SKIP LOCKED`. Cancellation requests become
`CANCELLED`; retryable jobs with attempts remaining return to `PENDING`; exhausted jobs become
`FAILED`. Recovery is an explicit service operation. V3.10 adds no scheduler daemon.

## Retry, Failure, And Results

Only `transient` failures can be retryable. Validation, authorization, configuration, and
internal failures are terminal. Backoff is bounded exponential delay, initially 30 seconds and
capped at 15 minutes; no service sleeps.

Persisted failure data is a short code, category, retryable flag, sanitized summary, and
timestamp. Job records and audit must not contain stack traces, authorization headers,
credentials, presigned URLs, or raw content. Successful jobs store a compact result type,
authoritative resource ID, and small metadata map. The owning domain table remains the result
source of truth.

## Reliable Dispatch Boundary

Creation, retry scheduling, and lease recovery insert a `job_dispatch_outbox` generation in
the same transaction as the job transition. Unpublished rows remain queryable after process
failure. Marking a dispatch published does not alter job authority, and duplicate delivery is
safe because a worker must still claim the PostgreSQL job.

V3.11 will publish these rows to SQS, define an identifier-only envelope, handle long polling
and visibility, acknowledge publication, and configure DLQ/redrive. V3.10 contains no SQS
client, worker loop, receipt handle, visibility extension, or AWS resource.

## Authorization And RLS

Humans use `job.read`, `job.create`, `job.cancel`, and `job.retry`. `job.execute` is excluded
from human roles and external service-account grants; only an explicit composition-owned
workload-identity grant can claim, complete, fail, recover, or publish dispatch state.

A future message supplies candidate identifiers only. The worker authorizes its workload
identity, establishes transaction-local tenant context, and resolves the persisted job under
forced RLS. The persisted row and claim token decide whether work may proceed. Missing or
mismatched context returns no job rows.

## Audit And Observability

Audit events cover creation, claim, success, failure, retry scheduling, cancellation,
cancellation request/acknowledgement, and lease recovery. They include actor, tenant scope,
job type, attempt, state, correlation, and safe result/error identifiers without payloads or
transport secrets.

Injected hooks expose created, started, succeeded, failed, retried, cancelled, duration, and
lease-recovery signals. High-cardinality IDs stay out of metric dimensions.

## Representative Index Job

`KnowledgeIndexBuildJobHandler` claims a typed job, validates its payload, calls the existing
V3.9 `HostedKnowledgeBundleService`, and stores only the resulting index-version reference. It
classifies adapter-declared transient failures for bounded retry and uses a safe terminal
failure for unexpected exceptions. It does not duplicate V3.9 logic.

## Version 2 Compatibility

Version 2 remains synchronous. Local `rag-build`, `rag-query`, triage, FastAPI, Gradio,
demo/user modes, filesystem ingestion, and in-process reindex status do not require hosted
jobs or PostgreSQL. Hosted and self-hosted behavior remain separate compositions.
