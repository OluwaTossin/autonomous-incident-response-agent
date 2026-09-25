# Incident history and triage investigation

V3.15 makes PostgreSQL incident, triage-run, result, evidence, job, and feedback records
usable through the hosted operator application. It extends the V3.12 resources rather than
adding a parallel history store or browser-only state model.

## Navigation and history

Workspace navigation links to a bounded incident list. The list is ordered by
`(created_at DESC, id DESC)`, uses opaque cursor pagination, and supports incident-state and
inclusive created-time filters. Each row shows source classification, lifecycle state,
severity, latest triage state, and durable run count. The repository obtains the latest run
and count in one PostgreSQL query to avoid per-row loading.

Severity, source, triage-state, and free-text incident filtering are deferred. The current
schema does not have all corresponding indexed incident-list projections, and V3.15 does not
add speculative indexes or arbitrary query syntax. The displayed values remain available
for operator inspection without implying an inefficient filtering contract.

Incident detail shows bounded source context and all runs newest first. The first row is
explicitly identified as the latest run. Job retries do not create a new TriageRun; attempt
count and next retry time belong to the same run. An operator re-triage action uses a fresh
idempotency key and creates a distinct durable run.

## Investigation view

Run detail polls only while queued or running, backs off to eight seconds, and does not poll
while the page is hidden. Backend terminal state is authoritative. The page shows safe job
state, attempt counts, retry schedule, timing, terminal failure category/summary, validated
triage result, severity, confidence, escalation recommendation, actions, and timeline.

For successful runs, V3.19 also shows read-only controlled action proposals derived from
the persisted recommended actions. The proposal section displays type, explicit target,
deterministic risk, reversibility, policy state, and policy reason. It never displays an
Approve or Execute control and never implies that a proposed action occurred. See
[`action-proposals.md`](action-proposals.md).

Evidence preserves ordered source/reason text and displays origin, document ID, document
version ID, knowledge-index version ID, chunk index, and score where available. These are
provenance identifiers, not object-store authority. V3.15 has no hosted document download
route, presigned URL, export, or raw object-key exposure; therefore the UI does not offer
download/export controls. A later phase must add authorization and audit before introducing
either capability.

AWS-backed run detail also exposes the immutable normalized operational-context snapshot:
collection status and window, integration/provider/region provenance, safe collector
diagnostics, metric context, redacted log excerpts, and truncation markers. The browser reads
persisted context only; it cannot initiate arbitrary CloudWatch queries or log searches.

Operators with `incident.create` may request a new triage run, transition the incident using
the existing domain state machine, cancel a non-terminal run, and submit bounded feedback.
Viewers receive the same authorized investigation data without mutation controls. UI hiding
is only an ergonomic measure: FastAPI authorization and transaction-local PostgreSQL RLS
remain the enforcement boundary.

## Security and compatibility

Browser traffic stays within the V3.13 same-origin BFF. The browser receives no bearer token,
API key, provider error, claim token, queue receipt, lease, object key, prompt, or local cache
path. Every mutation requires the session-bound CSRF token. Dynamic pages and API responses
remain `no-store`.

Operational context is incident/run scoped and remains separate from uploaded documents and
the workspace knowledge index. Version 2 synchronous triage, static frontend, CLI, Gradio,
filesystem workspace, local FAISS, JSONL audit, and metrics behavior are unchanged.
