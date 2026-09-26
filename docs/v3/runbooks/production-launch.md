# Hosted production launch runbook

This runbook is a procedure, not authorization. Use synthetic data only and never paste secrets.

## Stop conditions

Stop on any release-identity mismatch, unresolved Critical/High finding, failed isolation/migration,
missing backup/restore or rollback evidence, destructive critical Terraform change, absent secret,
unhealthy ECS/readiness, non-empty unexpected DLQ, broken auth/ingestion, missing alarm, integrity
risk, or absent protected-environment approval.

## Pre-launch

1. Name release, migration, rollback, security, and incident owners; approve a provisional
   observation window and V2 fallback retention period.
2. Freeze Git SHA, API/worker/web digests, Alembic revision, environment, and release manifest.
3. Verify branch protection, protected `production` environment reviewers, GitHub OIDC roles,
   remote Terraform backend, ECR artifacts, DNS/ACM ownership, and read-only operator access.
4. Run metadata-only secret checks for DB runtime/master flow, web session, cursor signing, LLM key,
   and worker grants. Do not read values.
5. Review security/adversarial reports and residual risks. Critical/High unresolved means stop.
6. Confirm current RDS backup/PITR, deletion protection, restore evidence, V2 backup/freeze plan,
   queues/DLQs, S3/KMS, Cognito, EventBridge, dashboards, alarms/actions, and quotas.
7. Initialize Terraform and produce a reviewed plan. Any unapproved critical replacement means stop.
8. Validate readiness evidence against the exact release. A prior release's evidence is invalid.

## Deployment and verification

1. Obtain explicit protected-environment approval for the exact release package.
2. Apply reviewed infrastructure with runtime services disabled.
3. Confirm immutable images and populated secrets; run migration task and require revision match.
4. Activate runtime only after migration succeeds. Wait for ECS circuit breakers/stability.
5. Verify API `/healthz`, API `/readyz`, web `/healthz`, ALB targets, and task definitions/digests.
6. Run dedicated synthetic Cognito PKCE login, `/v3/me`, workspace access, logout/revocation.
7. Run `AIRA_SYNTHETIC_DO_NOT_ESCALATE` incident/triage and verify evidence and durable audit.
8. Exercise synthetic EventBridge ALARM/OK, context collection, replay handling, and queue health.
9. Verify proposals/approvals/intents remain non-executing. No V4 connector may be present.
10. Review dashboards, required alarms, SLO burn, DB, queue age, DLQs, worker/ingestion success,
    quotas, auth failures, and security signals throughout the observation window.

## Rollback and fallback

Rollback when readiness fails, auth breaks, sustained 5xx occurs, revision/digest drifts, queue
processing stops, synthetic checks fail materially, or a security signal appears. Restore the prior
exact manifest digests and require ECS stability/smoke checks. Never run an Alembic downgrade.

Before the first V3-only write, traffic may return to the still-frozen V2 endpoint. After that write,
stop V3 writers and invoke a reviewed reconciliation plan; simple fallback is unsafe. Preserve all
V3 data and evidence. Do not delete a failed deployment to conceal it.

## Final decision record

Record `CODE_READY`, `REHEARSAL_READY`, `LIVE_VALIDATED`, and `GO_LIVE_APPROVED` independently,
plus validator output, approver reference, exact release identity, observation result, conditions,
and rollback trigger. `NO_GO` is the default when any required evidence is missing.
