# Hosted Incident and Asynchronous Triage API

V3.12 adds a hosted API boundary without changing the Version 2 synchronous
`POST /triage` path. Hosted routes use V3.4 request authentication, V3.5
authorization, sealed `AuthorizedTenantContext`, PostgreSQL, and the V3.10/V3.11
job/outbox worker plane. Browser sessions remain V3.13 work.

## Route Contract

All hosted routes are scoped below:

```text
/v3/organizations/{organization_id}/workspaces/{workspace_id}
```

The resources are:

```text
POST  /incidents
GET   /incidents
GET   /incidents/{incident_id}
PATCH /incidents/{incident_id}/state
POST  /incidents/{incident_id}/triage
GET   /triage-runs
GET   /triage-runs/{triage_run_id}
GET   /triage-runs/{triage_run_id}/result
GET   /triage-runs/{triage_run_id}/evidence
POST  /triage-runs/{triage_run_id}/cancel
POST  /triage-runs/{triage_run_id}/feedback
```

Path organization and workspace IDs are authorization candidates only. The application
authorizes authenticated `ActorContext` before issuing the sealed tenant context used for
PostgreSQL transaction-local RLS settings. Service accounts need explicit grants.

Incident input is bounded and rejects extra fields. It accepts title, description,
service, environment, source metadata, observation time, an optional severity hint, and a
bounded metric summary. Credentials, headers, unrestricted log archives, and arbitrary
JSON are not accepted. State changes use the existing domain state machine and cannot
reopen an incident.

Lists use opaque cursors over `(created_at DESC, id DESC)`, accept at most 100 records,
and expose incident-state, triage-state, incident, and bounded incident-created-time filters.
The incident history projection includes the latest run and run count in one query; the
triage history projection joins its durable job in one query. Responses exclude database ownership fields,
queue receipts, dispatch metadata, leases, claim tokens, object keys, cache paths, prompts,
and provider errors.

V3.15 adds operator-safe history fields. Incident rows expose source classification,
severity hint, latest run state/result summary, and run count. Triage rows expose job state,
attempt count, maximum attempts, next retry time when applicable, safe failure category and
summary, and persisted severity/confidence/escalation. Retries keep the same run ID; a new
operator re-triage request uses a new idempotency key and creates a distinct run.

## Asynchronous Request

`POST /incidents/{incident_id}/triage` requires `Idempotency-Key` and returns `202
Accepted` with durable `incident_id`, `triage_run_id`, `job_id`, and current states.
`triage_id` is exactly the string form of `triage_run_id`; there is no second identifier.

One PostgreSQL transaction reloads the authorized incident, inserts the queued TriageRun,
inserts the versioned TRIAGE Job and dispatch outbox row, and writes the attributable
`triage.requested` audit event. The version 1 payload contains only `incident_id` and
`triage_run_id`; tenant authority and incident content are not copied into the payload or
SQS envelope.

Durable job uniqueness scopes a hash of the client key to the tenant and incident. A
repeated equivalent request returns the existing run and job. A payload/hash conflict
returns `409`.

## Worker Lifecycle

The trusted worker reloads Job, TriageRun, and Incident under its explicit system grant.
Claiming the Job and moving the TriageRun from queued to running share one short
transaction. The worker commits before resolving the active knowledge bundle, acquiring
the verified FAISS cache, running retrieval, or calling the LLM.

The handler invokes the shared V3.1 `execute_triage` and LangGraph pipeline with a hosted
`RetrievalContext`. It validates `TriageOutput` and forces its compatibility ID to the
durable TriageRun ID. It does not duplicate the reasoning graph.

Success uses one transaction to validate the current claim and lease, validate the
TriageRun version/state, replace ordered evidence, persist the validated result, and mark
both TriageRun and Job succeeded. A stale worker cannot write a result. There is no
committed-result/job-running window.

Duplicate terminal messages are ignored by the V3.11 processor. Lease recovery keeps the
same TriageRun; a scope reconciliation pass repairs running-to-queued drift before
redispatch and repairs terminal failed/cancelled drift after a crash.

## Evidence, Failure, And Cancellation

Evidence is stored separately in result order. Rows retain safe source/reason text,
origin, document and document-version references, knowledge-index version, chunk index,
and score. They do not store presigned URLs, S3 keys as authority, credentials, or local
cache paths. Forced RLS and tenant-consistent foreign keys apply to all records.

Worker failures use deterministic Job categories: validation, authorization,
configuration, transient dependency, or internal. A missing active knowledge index is a
terminal configuration failure. Only explicitly transient failures retry, with attempts
and backoff owned by the Job. Exhausted failures expose only a safe code, category, and
summary. Model output never selects retry behavior.

Pending cancellation atomically cancels Job and TriageRun. Running cancellation is
reported as requested until the worker reaches a checkpoint and atomically acknowledges
both states. The API does not promise immediate interruption of an in-flight provider
call.

## Audit, Compatibility, And Deferred Work

Durable audit events cover incident creation/state changes and triage requested, started,
succeeded, failed, retried, and cancelled transitions. They contain actor, correlation,
safe IDs, and state, never prompts, documents, queue bodies, claims, or secrets. Observer
hooks emit bounded outcomes without entity or tenant IDs as metric dimensions.

Version 2 keeps API-key authentication, synchronous `/triage`, CLI and Gradio execution,
filesystem workspaces and FAISS, JSONL audit, and existing metrics. It is not routed
through PostgreSQL or SQS.

V3.13 owns the hosted Next.js session, Cognito PKCE callback, cookies, CSRF, refresh, and
operator UI. V3.15 history behavior is described in
[`incident-history.md`](incident-history.md). CloudWatch/EventBridge intake, AssumeRole context collection, and enrichment
remain V3.16-V3.18. Action proposals and approvals remain V3.19-V3.21.
