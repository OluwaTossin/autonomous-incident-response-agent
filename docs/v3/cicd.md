# Hosted CI/CD and release promotion

## Pipeline architecture

V3.26 separates validation, artifact creation, environment deployment, and rollback:

```text
pull request -> CI only (no AWS credentials)

main -> CI -> build hosted images once -> scan -> push immutable dev SHA tags
     -> release manifest
     -> deploy development -> migrate -> activate -> smoke -> qualified manifest
     -> production plan
     -> protected production approval
     -> apply reviewed disabled-runtime plan
     -> copy exact image digests to production ECR
     -> migrate -> activate -> smoke
```

The hosted Python image is built once. API and worker repositories receive the same image
manifest and therefore the same digest; ECS selects different commands from that image. Web is
built once separately. Production pulls the development-qualified images by digest and pushes the
same manifests into production repositories. It never runs `docker build` and never deploys
`latest`.

## Workflows

| Workflow | Trigger | AWS identity | Responsibility |
| --- | --- | --- | --- |
| `ci.yml` | PR, `dev`/`main` push, reusable call | None | Application, PostgreSQL/RLS, frontend, Terraform, security, and image-build validation |
| `release-build.yml` | `main` push or manual dispatch on `main` | Development release role through OIDC | Re-run CI, build/scan/publish immutable images, SBOMs, release manifest |
| `deploy-dev.yml` | Manual immutable release run ID | Development deploy role through OIDC | Runtime-off plan/apply, secret checks, migration, activation, stability/smoke, qualification |
| `deploy-production.yml` | Manual development deployment run ID | Production plan/deploy roles through OIDC | Reviewable plan, protected approval, exact digest promotion, migration, activation, smoke |
| `rollback-hosted.yml` | Manual prior deployment run ID | Selected environment deploy role through OIDC | Application digest rollback only after schema-compatibility acknowledgement |

Concurrency groups permit only one deployment per environment. Pull-request validation supersedes
older runs for the same PR and never receives `id-token: write`, environment secrets, or AWS
credentials.

## GitHub repository prerequisites

These settings are external prerequisites and are not configured or claimed by this repository:

- Bootstrap the V3.22 remote state backend, OIDC roles, and development ECR repositories through a
  separately reviewed infrastructure change before the first hosted release. The normal release
  workflow deliberately cannot create its own trust boundary or image destination.
- Protect `main`: require PR review and the CI checks, disallow force pushes, and restrict direct
  pushes.
- Create `development`, `production-plan`, and `production` GitHub Environments.
- Configure required human reviewers and prevent self-review on `production`. Production AWS
  credentials become available only after this environment gate.
- Keep the production plan role read-only except for state-lock access. Keep development and
  production deploy roles distinct, even when accounts initially coincide.
- Restrict artifact and workflow administration to trusted repository maintainers.

Environment variables are deployment-owned, non-secret configuration:

- `AWS_REGION`, `AWS_DEPLOY_ROLE_ARN`; `production-plan` uses `AWS_PLAN_ROLE_ARN`.
- `API_ECR_REPOSITORY`, `WORKER_ECR_REPOSITORY`, `WEB_ECR_REPOSITORY`.
- `TF_STATE_BUCKET`, `TF_STATE_LOCK_TABLE`, `TF_STATE_KEY`.
- `ROUTE53_ZONE_ID`, `WEB_HOSTNAME`, `API_HOSTNAME`, `COGNITO_DOMAIN_PREFIX`.

Repository-level production promotion validation also needs `DEV_API_ECR_REPOSITORY`,
`DEV_WORKER_ECR_REPOSITORY`, and `DEV_WEB_ECR_REPOSITORY`. Production ECR repository policies must
grant its deploy role read access to those exact development repositories when accounts differ.
No long-lived AWS access keys are workflow inputs or secrets.

## GitHub OIDC trust

Deployment roles trust `token.actions.githubusercontent.com` with audience `sts.amazonaws.com`.
Trust must bind the exact repository and environment subject. Representative subject conditions
are:

```text
repo:OluwaTossin/autonomous-incident-response-agent:environment:development
repo:OluwaTossin/autonomous-incident-response-agent:environment:production-plan
repo:OluwaTossin/autonomous-incident-response-agent:environment:production
```

The production role must not trust arbitrary branches, repositories, or wildcard environment
subjects. The plan role needs read/plan and backend-lock permissions; the deploy role additionally
needs reviewed ECR push, Terraform apply, ECS migration/run/describe, service wait, Secrets Manager
metadata, and CloudWatch log access. It must not receive customer remediation permissions.

## Release manifest and provenance

`scripts/deploy/release_manifest.py` validates a versioned JSON manifest containing the exact Git
SHA, Terraform SHA, workflow run ID, source repository/ref, Alembic head, ECR repositories, and
image digests. API and worker digests must match. Development and production deployments append
qualification records with workflow run and Terraform state serial.

This records provenance; it is not cryptographic signing, SLSA attestation, or proof of builder
identity beyond GitHub workflow and repository controls. Release, SBOM, and scan artifacts are
retained for 30 days; reviewed production plans for 3 days; production deployment manifests for
90 days. Artifacts contain no credentials or secret values.

## Terraform and migration ordering

Remote S3 backends remain authoritative. Deployment initializes the fixed environment root and
uses environment-owned backend values. The production plan is generated by a separate plan role,
stored with a checksum and human-readable rendering, and applied unchanged after the protected
`production` approval.

Every normal deployment follows this order:

1. Validate the immutable release and exact source workflow.
2. Plan and guard Terraform with `enable_runtime_services=false`.
3. Apply that exact runtime-disabled plan.
4. Ensure exact images are present and every expected runtime secret has one `AWSCURRENT` version.
5. Start the one-off private migration task using the release API digest and dedicated migration
   role.
6. Verify the image Alembic head equals the manifest head, log current/target revisions, wait with
   a 20-minute bound, and require exit code zero.
7. Only after success, plan and guard `enable_runtime_services=true`, then apply.
8. Wait up to 20 minutes for all ECS services and circuit breakers, then check web `/healthz`, API
   `/healthz`, and API `/readyz` with bounded retries.

A failed migration stops the job before activation. Deployments never downgrade Alembic, purge
queues, delete infrastructure, or retry forever. Expand/contract migrations are required when old
and new tasks may overlap during ECS rolling replacement.

The activation apply starts API, worker, dispatcher, alert ingestion, and web together after the
schema gate; there is no claimed ordering among those services. This is safe only while every
released service is backward-compatible with the migrated schema. Existing queue contents are
preserved and workers resume from the durable queues.

## Destructive plan boundary

`scripts/deploy/terraform_plan_guard.py` parses `terraform show -json`; it does not scrape plan
text. Routine development, production, activation, and rollback plans fail when destroy/replace is
proposed for RDS, S3 buckets, KMS keys, Cognito pools/clients, or SQS queues. Other destructive
changes remain visible in the plan summary for human review.

Critical replacement requires a separate break-glass infrastructure procedure, impact/data-loss
analysis, backups, named approvers, and an independently reviewed plan. There is intentionally no
workflow input that bypasses this guard. RDS deletion protection, private storage, and KMS deletion
windows remain independent defenses.

## Security gates

Release CI blocks failed Ruff/tests/RLS/auth/session checks, Terraform validation, real secret
findings, known fixed HIGH/CRITICAL dependency or image findings, and Bandit HIGH findings. npm and
pip production audits are blocking. Checkov MEDIUM/accepted findings and full Bandit reports are
retained for review rather than silently suppressed or blindly fixed.

No release exception is encoded as a free-form workflow input. A temporary exception requires a
reviewed source change naming the advisory, owner, expiry, and compensating control.

## Rollback and limitations

Rollback selects a previous successful environment deployment artifact, requires an exact digest
and explicit schema-compatibility acknowledgement, uses the protected environment, runs the same
destructive-plan guard, and performs no rebuild or database downgrade. ECS circuit breakers provide
automatic application rollback during unhealthy rolling deployment.

GitHub Environment protection, AWS roles/repository policies, remote backends, secrets, DNS, and
live smoke behavior require external configuration and V3.29 staging rehearsal. The first release
also requires the separately reviewed bootstrap described above; bootstrap is not part of routine
application deployment. V3.26 does not run Terraform apply, push an image, assume a deployment
role, or deploy an environment while the workflow code is being implemented. Artifact signing,
synthetic authenticated smoke tests, and external notifications remain deferred.
