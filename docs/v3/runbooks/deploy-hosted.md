# Hosted Deployment And Rollback Runbook

## Preconditions

Use a reviewed remote S3 backend configuration with locking, an AWS planning/deployment
role for the target account, a controlled DNS zone, and immutable API/worker/web image
digests. Never put credentials or secret values in `.tfvars`.

After infrastructure apply is separately approved, populate these generated Secrets
Manager secrets out of band: Python (`postgresql+psycopg://`) and Node (`postgresql://`)
URLs for `aira_app` with TLS required, the LLM API key, base64 32-byte web session key,
and worker route JSON with explicit organization,
workspace, integration, AWS account, and region bindings.

## Deployment Order

1. With `enable_runtime_services = false`, review and apply the remote-backend Terraform
   plan under a separate AWS approval. This creates repositories and infrastructure while
   every hosted ECS service remains at desired count zero.
2. Build, scan, and push API, worker, and web images; record immutable digests.
3. Populate or rotate secret versions without printing values.
4. Replace placeholder digests and register digest-pinned task definitions through a
   reviewed plan/apply, keeping `enable_runtime_services = false`.
5. Run the one-off migration task in private application subnets. Wait for exit code zero
   and verify `alembic current` separately.
6. Set `enable_runtime_services = true`, review the resulting plan, and apply it to start
   API, web, worker, dispatcher, and alert receiver services.
7. Verify API `/healthz` plus database-backed `/readyz` through HTTPS.
8. Confirm worker, dispatcher, and alert receiver queues poll and DLQs remain empty; then
   complete Cognito PKCE login and server-side bootstrap through the web service.
9. Instantiate the customer EventBridge module once per supported region, then add the
   corresponding route and customer account to the reviewed platform plan.
10. Run synthetic incident, triage, alert, tenant-denial, and V2 regression smoke tests.

Do not start tasks against an incompatible schema. Prefer expand-and-contract migrations
that permit previous and next application revisions to overlap.

## Rollback

Roll services to the previous immutable task-definition revision and image digest. Keep
the schema when it remains backward compatible. Database downgrade is not the default:
use a forward fix or restore to an isolated database after reviewed data-loss analysis.
Preserve queue messages and immutable bundles while application code rolls back.

For a failed migration, stop rollout, retain migration logs, and decide between a forward
migration and point-in-time restore. Never run a destructive downgrade merely to match an
old image.

## Health And Failure Signals

- Web liveness: `/healthz`.
- API liveness: `/healthz`; readiness: `/readyz` with `SELECT 1`.
- ECS deployment circuit breakers roll back unhealthy deployments.
- Job and alert DLQ depth alarms indicate durable transport failure.
- ALB 5xx and RDS CPU alarms are initial signals, not the V3.23 SLO suite.

V3.22 performed validation and local builds only. It did not run Terraform apply or a live
AWS deployment.
