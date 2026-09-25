# AWS integration onboarding

V3.16 adds workspace-scoped AWS account onboarding for future CloudWatch alert delivery
and context collection. It does not create customer resources, receive EventBridge events,
query incident context, or retain AWS credentials.

## Trust and lifecycle

```text
Admin
  -> AIRA creates integration + random ExternalId
  -> Admin creates an IAM role in customer AWS
  -> Admin configures RoleArn
  -> AIRA STS AssumeRole with ExternalId
  -> STS GetCallerIdentity
  -> bounded CloudWatch/Logs capability probes
  -> AIRA stores sanitized verification results
  -> integration READY
```

The lifecycle is `draft -> pending_verification -> ready/error -> disabled`. A failed
verification preserves configuration and may be retried. Account, role, or region changes
clear prior verification and require re-verification. Verification completion compares the
configuration version loaded before AWS calls; a stale verifier cannot certify changed
configuration. Disabled records are retained and cannot be used by later runtime phases.

ExternalId is generated server-side with cryptographic randomness and is unique in the
database. AIRA accepts no customer access key, secret key, session token, or console
credential. Verification obtains a 15-minute STS session, uses it for identity and bounded
probes, and discards it without persistence or logging.

Only the standard `aws` partition is supported initially. Account IDs are exactly twelve
digits. Role ARNs must be IAM role ARNs in the configured account. Caller identity must be
an assumed-role ARN for that account and role. Regions are explicit, normalized, sorted,
deduplicated, and limited to twenty; later operations must stay inside this allowlist.

Multiple AWS integrations are allowed per workspace, including the same account when teams
need different roles, region boundaries, or purposes. V3.16 does not impose a speculative
single-account uniqueness constraint.

## Customer role policies

The trust document uses only the deployment-configured
`AIRA_AWS_TRUSTED_PRINCIPAL_ARN`, `sts:AssumeRole`, and the integration's exact ExternalId.
Local tests inject a non-production principal. Hosted composition must fail configuration
when the real deployment principal is absent; V3.22 owns provisioning that principal.

The generated permission example has no wildcard actions. It groups the explicit read
operations anticipated by V3.17/V3.18:

- CloudWatch alarms and metrics reads;
- CloudWatch Logs describe, event-read, and Logs Insights query operations.

These AWS APIs do not consistently support resource-level authorization for list/describe
and metric operations, so the example uses `"Resource": "*"` where required by AWS IAM
semantics. This does not grant mutation operations. Customers should still review and
narrow log-group resources where their policy tooling and chosen APIs permit it.

READY requires successful AssumeRole, matching caller identity, and three mandatory probes
in every configured region: `DescribeAlarms`, `ListMetrics`, and `DescribeLogGroups`. Probe
responses are not retained as resource inventory. Safe result codes distinguish role trust,
account mismatch, missing alarm/metric/log permissions, throttling, and network failure;
raw provider exceptions never reach the browser.

## Authorization and data flow

`integration.read` allows status reads. `integration.manage`, held by Owner/Admin in the
approved V3.5 matrix, controls trust-artifact reads, create, update, verify, and disable.
The browser uses the existing secure session and same-origin BFF; all mutations retain CSRF
protection. FastAPI rebuilds ActorContext, authorizes the workspace, creates sealed tenant
context, and relies on forced PostgreSQL RLS. URL identifiers and frontend role labels are
not authority.

`aws_integrations` stores account, role, ExternalId, regions, lifecycle/version, sanitized
verification, timestamps, and actor attribution. It stores no temporary credentials. Audit
events cover creation, configuration, verification success/failure, and disable. Observer
signals contain only low-cardinality event/outcome values, not tenant, account, workspace,
or integration IDs.

## Alert delivery

V3.17 consumes authenticated CloudWatch Alarm State Change events through the machine-only
contract documented in [`alert-ingestion.md`](alert-ingestion.md). Delivery requires a READY
integration and validates the persisted account, configured region, and alarm-read
capability. Event JSON never selects tenant scope.

## Phase boundaries

V3.17 provides the application intake contract but does not provision EventBridge. V3.18
uses only verified capabilities and configured regions for bounded incident context
collection. V3.22 owns the production AIRA workload principal, EventBridge resources,
network/IAM deployment, and runtime configuration. No Terraform or live AWS change is part
of V3.16 or V3.17.
