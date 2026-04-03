# Terraform — AWS (Phase 10)

Modular layout under [`modules/`](modules/) and **environment roots** [`envs/dev`](envs/dev/) and [`envs/prod`](envs/prod/). **Remote state:** [`bootstrap/`](bootstrap/) provisions **S3 + DynamoDB** (default **eu-west-1**); each env uses [`backend.hcl`](envs/dev/backend.hcl.example) at `terraform init`.

| Module | Role |
|--------|------|
| `vpc` | VPC, public subnets (2 AZs), IGW, routes (Fargate tasks use **public IP**; no NAT in this lean cut) |
| `security_groups` | ALB ingress (80/443); ECS tasks only from ALB on API port |
| `ecr` | API image repository + lifecycle |
| `alb` | Internet ALB, target group (`ip`), health check `GET /health` |
| `ecs_fargate_api` | ECS cluster, Fargate service, task + execution IAM, CloudWatch logs, **SSM Parameter Store** secrets as container env (see `ssm_secrets` / `openai_api_key_ssm_parameter` in each env) |
| `frontend_static_cdn` | Phase 12 — S3 bucket for Next.js static export; optional CloudFront (HTTPS) vs S3 website (HTTP) via `enable_triage_ui_cloudfront` |
| `monitoring` | Phase 13 — CloudWatch dashboard (ALB + ECS + triage log metrics), ALB 5xx / unhealthy-target **alarms**, **log metric filters** on `/ecs/…-api` |

## Credentials

Terraform and the AWS provider **do not read** repo-root `.env`. Either:

- `export AWS_REGION=… AWS_ACCESS_KEY_ID=… AWS_SECRET_ACCESS_KEY=…` (or use `AWS_PROFILE`), or  
- `aws configure`, then ensure `AWS_REGION` is set for the provider default.

Same variables are documented in [`.env.example`](../../.env.example) for convenience; load them into your shell before `terraform` commands.

**CI:** `terraform fmt -check` and `terraform validate` run in GitHub Actions — see [`docs/deploy/ci.md`](../../docs/deploy/ci.md).

## Remote state (S3 + DynamoDB)

1. **Once per account/region** — create the bucket and lock table (bootstrap keeps **local** state):

   ```bash
   cd infra/terraform/bootstrap
   terraform init && terraform apply
   ```

2. **Per env** — copy the snippet from `terraform output backend_hcl_snippet_dev` (or `_prod`), or copy [`envs/dev/backend.hcl.example`](envs/dev/backend.hcl.example) → **`backend.hcl`** and replace `YOUR_ACCOUNT_ID` / names with bootstrap outputs.

3. **Init** (from `envs/dev` or `envs/prod`):

   - **Existing local `terraform.tfstate`:**  
     `terraform init -backend-config=backend.hcl -migrate-state`
   - **New clone / state already in S3:**  
     `terraform init -backend-config=backend.hcl`

`backend.hcl` is **gitignored**; only `*.example` is committed.

**Region:** `aws_region` in `terraform.tfvars` must stay the region where resources were created (**do not** switch e.g. `eu-west-1` → `us-east-1` on an existing state without a planned migration or destroy). SSM secrets and the remote state bucket must use the **same** region as the stack.

**Dev vs prod state:** one shared bucket; **separate objects** — `aira/terraform/state/development.tfstate` and `aira/terraform/state/production.tfstate` (see [`bootstrap/README.md`](bootstrap/README.md)).

## Dev (first apply)

```bash
cd infra/terraform/envs/dev
cp terraform.tfvars.example terraform.tfvars   # edit: aws_region (must match backend region), SSM paths
terraform init -backend-config=backend.hcl     # add -migrate-state if moving local state
terraform plan
terraform apply
```

**SSM Parameter Store:** define secrets in `terraform.tfvars` — either `openai_api_key_ssm_parameter` (sets `OPENAI_API_KEY`) or a list `ssm_secrets` mapping **env var names** → **parameter paths** (each path starts with `/`). Create each as **SecureString** in the same region; `terraform output ssm_container_secrets` shows the full list. Details: [`docs/deploy/aws-ecs.md`](../../docs/deploy/aws-ecs.md).

**ECR + ECS rollout:** use **[Phase 11](#phase-11--push-image-and-roll-out-ecs)** below and [`docs/deploy/aws-ecs.md`](../../docs/deploy/aws-ecs.md).

**Bootstrap without a runnable image:** set `api_desired_count = 0` in `terraform.tfvars` so apply succeeds; scale up after push.

## Prod

Same flow from [`envs/prod`](envs/prod/) with stricter defaults (`alb_enable_deletion_protection`, higher `api_desired_count`, longer log retention). Tighten `alb_ingress_cidr_ipv4` when you front the ALB with CloudFront or a known egress range.

## Validate (no AWS apply)

From repo root:

```bash
cd infra/terraform/envs/dev && terraform init -backend=false && terraform validate
cd ../prod && terraform init -backend=false && terraform validate
```

Run the second line from `infra/terraform/envs` so `../prod` resolves to `envs/prod`.

## Phase 11 — push image and roll out ECS

After `terraform apply`, build the RAG index locally (`uv run rag-build`), then from repo root:

```bash
./scripts/aws/push_api_to_ecr.sh dev
```

The script pushes an **immutable tag** plus **`:latest`** and runs **`terraform apply`**; ECS uses the **digest** of **`:latest`** (no **`api_image_tag`** in tfvars). See **[`docs/deploy/aws-ecs.md`](../../docs/deploy/aws-ecs.md)** for SSM, prod bootstrap, and env vars (`TF_APPLY_AUTO_APPROVE`, `PUSH_ONLY`, etc.).

