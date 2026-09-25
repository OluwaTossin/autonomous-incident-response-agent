# Version 3 SQS Transport And Hosted Worker

V3.11 adds at-least-once SQS delivery around the V3.10 PostgreSQL job model. It
does not create queues, DLQs, IAM roles, ECS services, or other AWS resources.
PostgreSQL remains authoritative for job state, tenant scope, attempts, retry
timing, claims, cancellation, and results. SQS visibility is transport
protection only and never proves execution ownership.

For `triage` jobs, V3.12 registers an optional lifecycle coordinator beside the typed
handler. It synchronizes Job claim/completion/failure/cancellation with TriageRun state and
performs scope reconciliation after lease recovery and before outbox publication.
Expensive retrieval and model calls remain outside database transactions.

## Message Contract

Schema version 1 contains only identifiers:

```json
{
  "schema_version": 1,
  "job_id": "uuid",
  "dispatch_id": "uuid",
  "dispatch_generation": 1,
  "routing_organization_id": "uuid",
  "routing_workspace_id": "uuid"
}
```

Forced tenant RLS prevents an unscoped application-role query from discovering
a job's tenant. Organization and workspace IDs are therefore untrusted routing
hints, not authority. The worker authorizes its verified workload identity for
the hinted scope, loads the exact persisted dispatch and job under RLS, checks
their persisted scope and generation, and uses that persisted job scope for
claim and execution. Forged hints either fail workload authorization or expose
no matching row. Messages never contain permissions, payloads, attempts, claim
tokens, content, credentials, URLs, or receipt handles.

## Outbox Publication

Creation, retry, and lease recovery still write one generation-unique outbox
row in the same transaction as the job transition. A dispatcher claims ready
rows with `FOR UPDATE SKIP LOCKED`, commits a short publication lease, sends the
message outside the transaction, and then acknowledges publication with the
claim token. Send failure releases the claim; process death lets it expire.

If send succeeds but acknowledgement does not, the row is published again
after claim expiry. This is intentional. Correctness depends on persisted job
generation and claim semantics, not exactly-once SQS delivery or FIFO
deduplication.

## Worker Flow

For each message the worker:

1. validates the strict schema;
2. re-authorizes its trusted workload identity;
3. loads the exact dispatch and job from PostgreSQL under forced RLS;
4. rejects stale generations and no-ops terminal or actively leased jobs;
5. claims a runnable job with the V3.10 claim token and lease;
6. executes an allowlisted handler selected from persisted `JobKind`;
7. commits success, retry, failure, or cancellation;
8. permits deletion only after that durable outcome is committed.

Malformed messages are retained for configured SQS redrive. Valid references
that cannot resolve or authorize are deleted without manufacturing job state.
An unknown persisted job kind fails closed through a sanitized terminal job
failure. The initial `index_build` handler delegates business work to the V3.9
bundle service.

## Leases, Visibility, And Cancellation

The heartbeat renews the PostgreSQL lease first using the current claim token.
Only then does it extend SQS visibility. A stale, expired, terminal, or
reclaimed job cannot renew. Visibility failure is observable but cannot grant
execution authority. If durable renewal fails, visibility extension stops and
the stale worker cannot complete the job.

Workers check cancellation before expensive handler work and through a handler
checkpoint callback. Cancellation is cooperative: operations that cannot stop
safely may finish their current unit, after which the worker records the
durable cancellation instead of success. No immediate interruption guarantee
is made.

## Retry And Crash Guarantees

`available_at` in PostgreSQL remains the retry clock. A retryable failure moves
the same job back to `PENDING`, increments its dispatch generation, and creates
a new outbox row. Old generations cannot create another attempt. SQS delay may
be added later only as an optimization.

- Outbox commit before send: another publisher claims the row later.
- Send before outbox acknowledgement: duplicate publication is safe.
- Receive before claim: visibility expiry redelivers the message.
- Claim before completion: lease recovery creates the next durable generation.
- Completion before delete: redelivery observes a terminal no-op.
- Retry before delete: the old generation is stale and cannot execute.
- Visibility expiry during an active job lease: another worker cannot claim.

DLQ placement does not change job state. Reconciliation compares PostgreSQL job
and dispatch state with transport redrive information. Authorized workload
replay clears publication state only for the current nonterminal generation,
writes a durable audit event, and republishes through the normal dispatcher.
Receipt handles and raw message bodies are never persisted or audited.

## Runtime And Configuration

The synchronous polling runtime uses SQS long polling, receives at most ten
messages, bounds work with a fixed thread pool, isolates message failures, and
stops accepting new batches on SIGINT/SIGTERM while allowing the current
bounded batch to finish. `app.composition.hosted_worker.build_hosted_worker`
is the explicit composition boundary; deployment supplies verified workload
identity, authorized scopes, the V3.9 index operation, PostgreSQL sessions, and
the injected SQS client. `app.worker.entrypoint.run_worker` is the process
entrypoint for that completed bootstrap.

Deployment settings cover queue URL, region, optional test endpoint, polling,
batch size, visibility, heartbeat, durable lease, concurrency, dispatcher
batch/lease, and boto timeout/retry bounds. AWS credentials use the normal
provider chain. They are not source settings or workspace configuration.

Injected observers expose bounded event/outcome/duration signals for outbox
pending/publication, receive, claim, success/failure/retry, duplicates, stale
dispatch, visibility failure, lease-renewal failure, and processing duration.
Job, organization, workspace, and dispatch IDs may be structured log fields,
but are never metric dimensions.

## Compatibility And Deferred Work

Version 2 remains synchronous and requires no PostgreSQL, SQS, worker, or
outbox. Its CLI, API, Gradio, filesystem ingestion, reindexing, and local FAISS
paths are unchanged.

V3.12 owns hosted incident/triage APIs and their durable result model. V3.22
owns encrypted SQS/DLQ resources, redrive policy, IAM, ECS task/service wiring,
autoscaling, and queue alarms. Production workload-identity bootstrap is bound
to those IAM resources; V3.11 does not pretend they are deployed.
