# Hosted security incident runbook

Use this runbook for suspected credential leakage, session/token compromise, cross-tenant access,
AWS role misuse, vulnerable dependencies, service-account compromise, or audit integrity concerns.
Do not include real secrets, customer content, or personal contact details in tickets or chat.

## First response

1. Assign an incident commander and scribe. Record UTC times, detection source, environment,
   suspected tenants, affected identities, and correlation IDs.
2. Preserve evidence before destructive action: relevant audit rows, redacted logs/traces, task
   definitions, image digests, Terraform revision, Cognito events, CloudTrail events, S3 versions,
   queue metadata, and database backup identifiers.
3. Classify severity. Cross-tenant disclosure, active privileged credential use, audit destruction,
   or uncontrolled infrastructure action is critical until disproved.
4. Stop expansion. Disable the narrowest affected integration, service account, session set,
   workload, route, or deployment. Do not broadly delete evidence or purge queues.
5. Escalate to the security and platform owners through the approved incident channel. Notify
   privacy/legal owners when regulated or personal data may be involved.

## Credential or API-key leak

1. Identify the exact secret and every workload that can read it. Never paste its value.
2. Revoke or rotate it at the provider, then update Secrets Manager through the approved process.
3. Restart only affected tasks and verify the old credential fails.
4. Search redacted logs, CloudTrail, provider audit, and source history for use and exposure.
5. If source history contains a real secret, revoke first, then use an approved history-rewrite
   process; do not assume deleting the current file removes the leak.

## Browser session or Cognito compromise

1. Revoke affected durable browser sessions in PostgreSQL; cookie deletion alone is insufficient.
2. Disable the Cognito user when identity compromise is suspected and revoke provider tokens.
3. Review memberships, workspace grants, approvals, feedback, downloads, and configuration changes
   attributable to the user.
4. Rotate the session encryption key only with incident-command approval because current rotation
   invalidates all hosted sessions.
5. Verify old sessions and refresh tokens fail and membership removal is enforced by the API.

## Service-account compromise

1. Disable the specific credential and authorization grants. Do not convert it into a human actor.
2. Review credential prefix, last-used metadata, source IP/provider logs, tenant scope, and every
   incident/job created under that actor.
3. Issue a replacement only after the integration owner confirms containment.
4. Verify service accounts still cannot approve consequential actions.

## Cross-tenant access suspicion

1. Treat as critical. Pause the implicated endpoint/worker path without modifying tenant evidence.
2. Preserve request IDs, actor ID, organization/workspace IDs, SQL transaction context, pooled
   connection identifiers, object keys, cache bundle identity, and queue/job IDs.
3. Reproduce only in an isolated environment with synthetic multi-tenant fixtures.
4. Test both application authorization and RLS independently. Inspect every related table, S3
   object, FAISS cache entry, log, trace, usage event, and presigned request.
5. Do not use migration-owner credentials for casual investigation. Exceptional access must be
   approved, time-bounded, and audited.
6. Keep the affected release blocked until scope, root cause, correction, and regression evidence
   are reviewed.

## AWS role or integration compromise

1. Disable the affected AIRA integration and customer trust relationship or ExternalId.
2. Review CloudTrail for broker-role and customer-role sessions, requested role ARN, ExternalId,
   region, API calls, and session tags.
3. Revoke temporary access by changing/removing customer trust and disabling the source role as
   appropriate. Do not alter unrelated customer roles.
4. Preserve EventBridge and SQS evidence. Quarantine suspicious messages rather than blindly
   redriving or deleting them.
5. Verify the broker path, configured role prefix, account, region, and least-privilege read policy
   before re-enabling.

## Vulnerable dependency or image

1. Record advisory ID, affected locked version/image digest, scanner version, reachability, and
   severity. Do not run forced or bulk upgrade commands.
2. Upgrade the smallest compatible dependency set, regenerate the lockfile or image digest, and
   run full regression and security scans.
3. If no fix exists, disable the reachable feature or record a named, expiring risk acceptance with
   compensating controls. Critical/high reachable findings block release.
4. Generate a fresh SBOM and retain scanner output with release evidence, not in customer logs.

## Audit preservation and recovery

- Audit and usage ledgers are append-only to the runtime role. Preserve database backups and WAL
  evidence before schema-owner investigation.
- Do not edit historical audit rows to make an incident appear resolved. Add corrective events.
- Restore into an isolated environment, verify checksums/counts and RLS, then obtain approval
  before any production recovery.
- Verify containment with revoked credentials, denied old sessions, clean scans, tenant-isolation
  tests, reviewed CloudTrail, and monitored synthetic requests.

## Closure

Record root cause, affected data/tenants, timeline, containment, recovery evidence, residual risk,
owners, and due dates. Update threat model, tests, runbooks, and controls. A security incident is not
closed solely because traffic recovered.
