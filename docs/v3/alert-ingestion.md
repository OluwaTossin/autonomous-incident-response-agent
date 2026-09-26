# CloudWatch alarm ingestion

V3.17 adds the durable application boundary for CloudWatch Alarm State Change events.
V3.22 selects the production transport: customer regional EventBridge rule -> central
AIRA EventBridge bus -> encrypted alert SQS queue/DLQ -> private alert receiver. It does
not query CloudWatch Logs or Metrics for incident context.

## Architecture and authentication

```text
CloudWatch Alarm
  -> customer EventBridge forwarding role
  -> account-allowlisted AIRA EventBridge bus
  -> encrypted SQS alert queue and private workload-identity receiver
  -> match EventBridge-generated account/region to deployment-owned route
  -> establish transaction-local tenant context
  -> load persisted READY AwsIntegration under forced RLS
  -> validate account, region, event schema, and alarm capability
  -> receipt + incident + triage run + job + outbox + audit transaction
```

The application route is:

```text
POST /internal/v1/organizations/{organization_id}/workspaces/{workspace_id}
     /integrations/aws/{integration_id}/cloudwatch-alarms
```

It is separate from browser `/v3` routes and does not use browser sessions or CSRF.
Deployment must inject an authenticated service-account or workload-identity actor. Human
actors are rejected. Organization and workspace path values are untrusted routing hints:
the machine actor must hold explicit permissions for that scope, and the persisted
integration must match it under forced RLS. Event JSON never supplies tenant authority.

The HTTP route remains a tested adapter, but the hosted AWS composition uses the SQS
receiver. Its route secret binds exactly one account/region to a persisted integration and
tenant scope; duplicate bindings fail startup. The ingestion service still revalidates the
persisted integration under RLS. See [`hosted-aws.md`](hosted-aws.md) and the customer
module under `infra/terraform/hosted/customer-eventbridge/`.

## Supported event contract

Only EventBridge schema version `0` with source `aws.cloudwatch` and detail type
`CloudWatch Alarm State Change` is accepted. Required normalized fields are:

- EventBridge event ID, account, region, and timestamp;
- one matching standard-partition CloudWatch alarm ARN in `resources`;
- bounded alarm name, current state, previous state, and reason.

The account, region, ARN, and alarm name must agree. The request body is limited to 64 KiB,
resources to 20 entries, and all retained strings are bounded. Additional provider fields
are ignored rather than persisted. Raw event bodies are not stored.

## State policy

- A newer transition into `ALARM` creates an `aws.cloudwatch` incident with deterministic
  `HIGH` ingestion severity and queues one asynchronous TRIAGE job.
- A newer `OK` transition resolves the correlated open or investigating incident.
- `INSUFFICIENT_DATA` is retained as alarm state but does not create an incident.
- An `ALARM` while the same alarm still has an active incident is acknowledged without
  creating duplicate work.
- A later `ALARM` after recovery creates a new incident and triage workflow.

The policy never infers severity from alarm-name text and never runs triage inline.
V3.18 may add bounded Logs/Metrics evidence but does not alter delivery authentication.

## Deduplication and ordering

`alert_event_receipts` has a durable unique key over tenant, integration, and EventBridge
event ID. It stores only normalized routing/state metadata, a canonical SHA-256 payload
hash, processing status, and resulting incident/triage identifiers. The same event ID and
same hash returns an idempotent duplicate acknowledgement. The same ID with different
content returns a conflict and never overwrites the original receipt.

`aws_alarm_states` stores the latest accepted source timestamp/state and correlated incident
for each integration plus alarm-identity hash. PostgreSQL transaction advisory locks
serialize different event IDs for the same alarm. Ordering uses source timestamp followed
by EventBridge event ID as a deterministic tie-breaker; older ordering keys are recorded as
stale and cannot roll state backward.

Receipt claim, state update, Incident, TriageRun, TRIAGE Job, dispatch outbox, and audit are
committed in one transaction. A durable failure rolls back all of them and produces a
retryable server response.

## Acknowledgements and audit

- New accepted or policy-ignored delivery: HTTP `202` with `accepted` or `ignored`.
- Previously processed identical delivery: HTTP `202` with `duplicate`.
- Missing/invalid authentication: `401` or `403`.
- Malformed/oversized payload: `422` or `413`.
- Unknown integration: `404`; readiness, account, region, or payload conflict: `409`.
- Unexpected persistence failure: `503`, allowing upstream retry.

Audit events record acceptance, duplicate/stale/policy decisions, incident creation,
automatic triage request, and applied recovery without raw payloads or credentials.
Observer signals use bounded event/outcome values; account, tenant, integration, alarm, and
event identifiers are excluded from metric dimensions.
