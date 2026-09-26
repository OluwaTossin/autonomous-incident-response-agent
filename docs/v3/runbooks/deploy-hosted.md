# Hosted Deployment And Rollback Runbook

## Preconditions

Use a reviewed remote S3 backend configuration with locking, an AWS planning/deployment
role for the target account, a controlled DNS zone, and immutable API/worker/web image
digests. Configure the GitHub Environments, reviewers, OIDC trust, variables, and branch
protection listed in `../cicd.md`. Never put credentials or secret values in `.tfvars`.

Before the first release, bootstrap the remote state backend, environment-scoped OIDC roles,
GitHub Environment protection, and development ECR repositories through a separately reviewed
infrastructure change. Routine release workflows do not bootstrap their own trust or state
infrastructure.

After infrastructure apply is separately approved, populate these generated Secrets
Manager secrets out of band: Python (`postgresql+psycopg://`) and Node (`postgresql://`)
URLs for `aira_app` with TLS required, the LLM API key, base64 32-byte web session key,
and worker route JSON with explicit organization,
workspace, integration, AWS account, and region bindings.

## Automated Deployment Order

1. Run `Build Hosted Release` from `main`. It reuses CI, builds the Python and web images
   once, scans them, pushes SHA-only tags to development ECR, and emits `aira-release`.
2. Run `Deploy Hosted Development` with that workflow run ID. It applies a guarded
   runtime-disabled plan, checks secret versions, runs and waits for the migration task,
   activates services only after exit code zero, waits for ECS stability, and performs
   unauthenticated health/readiness smoke tests.
3. Inspect its `aira-development-release` manifest and the development environment.
4. Run `Promote Hosted Production` with the successful development run ID. The read-only
   `production-plan` job creates the plan artifact. Review that plan before approving the
   protected `production` job.
5. Production applies the exact runtime-disabled plan, copies the exact development image
   digests into production ECR without rebuilding, checks secrets, runs migration, then
   activates and smoke-tests services.
6. Confirm queue/DLQ health, Cognito PKCE sign-in, deployment alarms, and the release
   manifest before closing the change.

Do not start tasks against an incompatible schema. Prefer expand-and-contract migrations
that permit previous and next application revisions to overlap.

## Rollback

Use `Roll Back Hosted Application` with the prior successful deployment run ID and exact
environment. Confirm schema compatibility explicitly. Production rollback still requires
the protected `production` approval. The workflow verifies that all prior digests exist,
blocks critical Terraform destruction, changes the application task definitions, waits
for ECS stability, and repeats smoke tests. It never rebuilds images or runs a database
downgrade.

For a failed migration, runtime activation is skipped automatically. Retain the migration
task ARN and CloudWatch logs, then choose a reviewed forward migration or point-in-time
restore into an isolated database. Never run a destructive downgrade merely to match an
old image.

If ECS activation fails, inspect circuit-breaker events and the exact task definition,
digest, and `build_sha`. The circuit breaker may restore the previous task definition;
otherwise use the rollback workflow after confirming schema compatibility. Do not purge
queues or destroy infrastructure.

If readiness fails after ECS stabilizes, leave the workflow failed, preserve logs and
artifacts, inspect RDS/session/dependency health, and roll back the application digest when
compatible. Do not bypass `/readyz` or loop indefinitely.

If the Terraform guard finds RDS, S3, KMS, Cognito, or SQS destruction/replacement, stop.
Routine deployment cannot override the guard. Use a separately approved break-glass plan
with backups, impact analysis, and service/data owners.

For a stuck GitHub deployment, cancel only after checking whether Terraform holds the
remote lock or ECS has a running migration task. Do not start an overlapping deployment;
the environment concurrency group intentionally serializes it.

For an emergency stop, set desired runtime state through a separately reviewed operational
change while preserving RDS, buckets, queues, logs, and audit evidence. Do not use rollback
as an infrastructure deletion mechanism.

## Health And Failure Signals

- Web liveness: `/healthz`.
- API liveness: `/healthz`; readiness: `/readyz` with `SELECT 1`.
- ECS deployment circuit breakers roll back unhealthy deployments.
- Job and alert DLQ depth alarms indicate durable transport failure.
- Aggregate dashboards, alarms, SLO inputs, and response procedures are defined in
  `../observability.md`, `../slos.md`, and `hosted-observability.md`.

V3.26 implements these workflows and validates them locally only. Repository environment
protection and AWS role/backend configuration remain external prerequisites. No Terraform
apply or live AWS deployment was performed while implementing V3.26.
