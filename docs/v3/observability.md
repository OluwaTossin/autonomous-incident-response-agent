# Hosted Observability

## Signal Boundaries

AIRA keeps four signal types distinct:

| Signal | Purpose | Identifier policy |
| --- | --- | --- |
| Structured logs | Detailed operational diagnosis | Protected IDs allowed; payloads and secrets prohibited |
| Metrics | Aggregate rates, latency, saturation, and health | Bounded dimensions only; tenant and entity IDs prohibited |
| Traces | HTTP and durable-job execution flow | Safe operation metadata only; no customer content or credentials |
| PostgreSQL audit | Durable business and security attribution | Authoritative actor, tenant, target, and correlation data |

For example, an approval audit event identifies the human and exact proposal. An
operational log records that persistence completed and its correlation IDs. The aggregate
metric counts the approved outcome. None substitutes for another.

Customer CloudWatch logs and metric datapoints collected by context enrichment are
tenant-scoped incident evidence. They never enter `AIRA/Hosted`, shared dashboards, or the
persistent knowledge corpus. Context collection continues to redact, bound, normalize,
and persist evidence before triage uses it.

## Structured Logs And Correlation

Hosted Python processes emit one-line JSON to stdout with `timestamp`, `level`, `service`,
`environment`, `build_sha`, `event`, and `message`. Request/job context may add
`correlation_id`, `request_id`, `organization_id`, `workspace_id`, `actor_id`,
`incident_id`, `triage_run_id`, `job_id`, `dispatch_id`, `integration_id`, and
`execution_intent_id`. Error records use bounded `error_category` values instead of raw
exception text as a metric label.

FastAPI accepts `X-Correlation-ID` only when it is a non-zero UUID, otherwise generates
one, returns it, and places it in request logs. Next.js applies the same validation,
returns the value from BFF responses, and forwards it to FastAPI. Incident and triage
creation place the request correlation in the durable domain record. The versioned,
identifier-only SQS envelope carries that correlation; workers re-authorize and compare it
to the authoritative PostgreSQL Job before use, then log it with job, incident, triage-run,
and dispatch IDs. EventBridge delivery uses its UUID event ID when valid and records both delivery and
durable result identifiers.

Next.js server logs cover missing/invalid sessions, CSRF failures, backend failures,
callback validation, session creation, and token-refresh failures. Tokens and session
contents remain server-only and are never fields in these records.

Central redaction runs before Python or Next.js log emission. It covers authorization and
cookie fields, passwords, API/session/access/refresh tokens, database URL passwords, AWS
access keys, private keys, and presigned URL fields. Logging raw incident text, customer
logs, prompts, model output, document content, STS credentials, or full claims is
prohibited.

## Metrics

Hosted application metrics use CloudWatch EMF and namespace `AIRA/Hosted`. EMF emits an
`Environment,Service` rollup plus the complete bounded dimension set. Allowed dimensions
are `Environment`, `Service`, `Operation`, `Result`, `JobType`, `Collector`, `Provider`,
`StatusClass`, `AlarmState`, `ProposalType`, `Risk`, and `Connector`. The adapter rejects
all other dimensions and explicitly rejects tenant, incident, triage, job, dispatch,
integration, proposal, approval, intent, alarm-name, and log-group identifiers.

Current application signals include:

- API request counts, duration, server errors, authentication failures, and authorization failures by named route/status class.
- Durable job lifecycle, worker outcome/duration, lease recovery, duplicate/stale delivery, and outbox publication outcomes.
- Triage request/start/success/failure/retry/cancellation and execution duration.
- Alarm receipt/outcome/failure and context-enrichment complete/partial/failure duration.
- Action policy/proposal, approval outcome/decision latency, and immutable execution-intent preparation/validation/lifecycle signals.

SQS supplies authoritative transport depth and oldest-message age. PostgreSQL remains the
authoritative job/outbox state. V3.23 does not infer durable state from queue metrics.
Aggregate context item/truncation metrics are emitted after redaction and bounding.
The dispatcher also samples a bounded PostgreSQL-authoritative pending count, oldest
pending age, and claimed count. Per-collector duration/item counts, runnable-job age, and
safe hosted LLM token/cost metrics are known measurement gaps to validate before V3.29;
they do not justify tenant dimensions or exposing customer evidence.

## Tracing

The hosted runtime uses OpenTelemetry API/SDK. HTTP requests and durable job execution are
span boundaries; the job span contains context enrichment and triage/LLM execution. Only
allowlisted attributes such as service, environment, route template, status class, job
type, operation, provider, and bounded error category are accepted. Raw URLs, IDs,
incident content, customer logs, documents, prompts, model responses, and secrets are
rejected.

`AIRA_OTEL_EXPORTER_OTLP_ENDPOINT` is optional and must be HTTPS in production. With no
endpoint, local development and tests require no collector. Sampling is controlled by
`AIRA_TRACE_SAMPLE_RATIO`; durable audit is never sampled.

## AWS Platform Signals

Terraform defines four aggregate dashboards: platform overview, asynchronous processing,
incident pipeline, and control plane. They combine bounded application signals with:

- ALB request, target/edge 5xx, response, connection, and healthy-target metrics;
- ECS/Container Insights running-task, desired-task, CPU, and memory metrics;
- SQS depth, in-flight count, oldest age, sent/received counts, and separate DLQs;
- RDS CPU, connections, memory, storage, latency, and deadlocks.

Alarms cover API/web unhealthy targets and 5xx, worker/dispatcher/alert task count, queue
age, both DLQs, dispatcher publish failures, RDS CPU/memory/storage, and API fast/slow
error-budget burn. `alarm_action_arns` is optional; no personal destination is hardcoded.
Alarm descriptions link to `runbooks/hosted-observability.md` and use platform SEV1-3,
which is independent of customer incident severity.

## Retention, Access, And Cost

Application log retention is configurable: current examples use 14 days in development
and 90 days in production. RDS exports PostgreSQL and upgrade logs, not verbose statement
logging. CloudWatch manages metric retention. Traces use configurable sampling and custom
metrics use standard resolution. Operators should watch log ingestion, metric count,
Container Insights, dashboards, and trace export as explicit cost drivers.

Internal dashboards and logs are restricted to AIRA operators through AWS IAM and are not
exposed in customer UI. Deployment correlation uses `build_sha`, immutable image digest,
ECS task-definition revision, and deployment-time error signals.

V2 API, CLI, Gradio, static frontend, and self-hosted metrics remain unchanged. The
OpenTelemetry SDK/exporter is installed through the `hosted` dependency extra and is not
included in the V2 production image. No Terraform apply or live AWS mutation is part of
V3.23.
