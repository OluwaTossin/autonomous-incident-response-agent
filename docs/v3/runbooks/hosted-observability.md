# Hosted Observability Runbook

All alarms are internal AIRA platform signals. They do not inherit customer incident
severity. Start with the platform, async, incident-pipeline, or control-plane CloudWatch
dashboard for the affected environment; then use `correlation_id` to join protected logs.
Do not print secrets, session data, customer evidence, or complete environment values.

## API Or Web Unhealthy

**Severity:** SEV1 when no healthy target; SEV2 for sustained target 5xx. **Impact:** hosted
API or web requests may fail. Check ALB healthy/unhealthy hosts, target 5xx, response time,
ECS desired/running tasks, deployment events, task exits, and `/healthz`; for API also
check `/readyz` and RDS connectivity. Compare task-definition revision, image digest, and
`build_sha` with the last healthy deployment. Mitigate with a reviewed rollback to the
previous immutable task definition or restore task capacity. Do not bypass readiness.
Escalate to the service owner for persistent 5xx or failed rollback. Recovery requires
healthy targets and successful representative HTTPS/BFF requests, not only running tasks.

## API Error Budget Burn

**Severity:** fast burn SEV1; slow burn SEV2. **Impact:** the 99.9% internal API objective
is being consumed rapidly. Check the API request/error metrics, status classes, bounded
error categories, ALB/RDS signals, and recent deployment. Confirm traffic volume so a
small denominator is not misleading. Mitigate the common dependency or roll back the
offending deployment through the deployment runbook. Escalate when burn persists across
two windows. Verify recovery by a falling error ratio and successful synthetic/real
requests; do not close solely because one alarm period cleared.

## Job Queue Backlog

**Severity:** SEV2. **Impact:** triage and index work is delayed. Check SQS visible,
in-flight, oldest-age, sent/received, worker running/desired count, worker failures,
retries, lease recovery, and RDS pressure. Confirm durable Job state before changing queue
messages. Restore worker capacity or roll back a failing worker deployment. Never purge or
redrive automatically. Escalate if oldest age continues increasing. Recovery requires
falling queue age and successful durable terminal jobs.

## Job DLQ

**Severity:** SEV2 for any message. **Impact:** one or more durable jobs exhausted
transport handling. Inspect DLQ metadata and protected logs by job/dispatch correlation,
then compare against authoritative PostgreSQL Job state. Correct the deterministic cause
before a reviewed redrive; do not delete evidence or bulk-redrive blindly. Escalate to the
worker owner for unknown or cross-version envelopes. Verify the job reaches the expected
durable state and DLQ depth returns to zero through an approved disposition.

## Alert Ingestion Backlog Or DLQ

**Severity:** SEV2. **Impact:** customer alarm incidents may be delayed. Check alert queue
age/depth, alert-receiver desired/running count, route configuration, EventBridge delivery,
authentication/authorization error categories, receipt state, and the separate alert DLQ.
Do not broaden account/region routing or trust event payload tenant claims. Restore the
receiver or correct a reviewed route/configuration issue. Do not auto-delete or redrive.
Escalate to the integration owner when cross-account delivery is failing. Verify a bounded
test alarm is durably accepted and duplicate handling remains idempotent.

## Worker Stalled

**Severity:** SEV2. **Impact:** async work cannot progress. Check ECS task/deployment
events, startup logs, mandatory configuration validation, SQS age, lease renewal/recovery,
and RDS/S3 dependencies. Replace failed tasks or roll back the worker revision. Do not
disable lease safety or mutate Job rows manually. Escalate on repeated exits or claim
loss. Verify desired task count, message consumption, and successful durable completions.

## Dispatcher Stalled

**Severity:** SEV2. **Impact:** committed outbox work is not reaching SQS. Check ECS task
count, `outbox_publish_total` outcomes, protected dispatcher logs, SQS/KMS permissions,
RDS health, and unpublished outbox rows. Restore connectivity or roll back the dispatcher;
allow claims to expire naturally when ownership is uncertain. Never mark rows published
without confirmed send. Escalate when pending age increases. Verify publish success,
acknowledgement, queue receipt, and declining backlog.

## RDS Pressure Or Unavailable

**Severity:** SEV1 when unavailable; SEV2 low storage; SEV3 sustained CPU/memory warning.
**Impact:** API, sessions, audit, ingestion, and jobs may fail. Check CPU, connections,
free memory/storage, latency, deadlocks, PostgreSQL logs, Performance Insights, Multi-AZ
events, and application persistence errors. Reduce avoidable load or restore a known-good
application revision. Scaling, failover, and restore require a separately reviewed AWS
change; never delete or recreate the database from this runbook. Escalate immediately for
unavailability or accelerating storage exhaustion. Verify `/readyz`, transaction success,
replication/Multi-AZ state, and stable resource levels.

## Cognito Or Auth Degradation

**Severity:** SEV2 when sign-in or refresh broadly fails. **Impact:** humans cannot start
or sustain sessions. Check safe callback/refresh/session logs, Cognito service health,
issuer/JWKS reachability, callback configuration, web/API task revisions, and database
session persistence. Never log tokens or claims wholesale. Roll back configuration or web
revision through the normal deployment process; do not weaken issuer, audience, PKCE,
cookie, or CSRF checks. Escalate to identity ownership if provider failure persists.
Verify a new PKCE login, refresh, logout/revocation, and authenticated BFF request.

## Operational Boundaries

Alarm actions are optional SNS ARNs supplied by deployment configuration. Diagnostic AWS
commands must use a read-only operator role and explicit environment/region. Any scaling,
redrive, rollback, failover, restore, or Terraform operation requires its normal approval.
V3.23 performed no live AWS apply and does not establish notification destinations.
