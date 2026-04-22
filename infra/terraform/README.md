# Terraform — AWS (Phase 10)

Modular layout under [`modules/`](modules/) and **environment roots** [`envs/dev`](envs/dev/) and [`envs/prod`](envs/prod/). **Remote state:** [`bootstrap/`](bootstrap/) provisions **S3 + DynamoDB** (default **eu-west-1**); each env uses [`backend.hcl`](envs/dev/backend.hcl.example) at `terraform init`.

| Module | Role |
|--------|------|
| `vpc` | VPC, public subnets (2 AZs), IGW, routes (Fargate tasks use **public IP**; no NAT in this lean cut) |
| `security_groups` | ALB ingress (80/443); ECS tasks only from ALB on API port |
| `ecr` | API image repository + lifecycle |
| `alb` | Internet ALB, target group (`ip`), health check `GET /health` |
| `ecs_fargate_api` | ECS cluster, Fargate service, task + execution IAM, CloudWatch logs, **SSM Parameter Store** secrets as container env (see `ssm_secrets` / `openai_api_key_ssm_parameter` in each env) |
| `frontend_static_cdn` | Phase 12 — S3 bucket for Next.js static export; **CloudFront (HTTPS) by default**; set `enable_triage_ui_cloudfront = false` for S3 website (HTTP) only |
| `monitoring` | Phase 13 — CloudWatch dashboard (ALB + ECS + triage log metrics), ALB 5xx / unhealthy-target **alarms**, **log metric filters** on `/ecs/…-api` |

## Credentials

Terraform and the AWS provider **do not read** repo-root `.env`. Either:

- `export AWS_REGION=… AWS_ACCESS_KEY_ID=… AWS_SECRET_ACCESS_KEY=…` (or use `AWS_PROFILE`), or  
- `aws configure`, then ensure `AWS_REGION` is set for the provider default.

Same variables are documented in [`.env.example`](../../.env.example) for convenience; load them into the shell before `terraform` commands.

**CI:** `terraform fmt -check` and `terraform validate` run in GitHub Actions (Terraform **1.9.4**) — see [`docs/deploy/ci.md`](../../docs/deploy/ci.md).

**`.terraform.lock.hcl`:** If CI fails with *cached package does not match checksums*, run **`terraform init -backend=false`** in the same env (or `terraform providers lock` for `linux_amd64` + darwin) with Terraform **≥ 1.9** and commit the updated lock file (several **`h1:`** lines per provider are normal).

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

### What is in Git vs local-only (cloners and collaborators)

| Artifact | In Git? | Purpose |
|----------|---------|---------|
| **`*.tf`**, **`modules/`**, **`envs/dev` / `envs/prod` roots** | Yes | Shared infrastructure code; safe to PR and review. |
| **`terraform.tfvars.example`**, **`backend.hcl.example`** | Yes | Templates — copy to **`terraform.tfvars`** / **`backend.hcl`** per machine or per AWS account. |
| **`terraform.tfvars`** | **No** (gitignored) | Your region, SSM paths, **`cors_origins`**, toggles (`enable_triage_ui_cloudfront`, …). Not secrets if you use SSM for keys, but still **environment-specific**. |
| **`backend.hcl`** | **No** (gitignored) | Remote state bucket, DynamoDB lock table, state **key** — ties this working copy to **one** AWS account/state object. |
| **`bootstrap/terraform.tfstate`** (local file) | **No** (gitignored if present) | Bootstrap stack uses **local** state; back it up if you manage shared buckets from one machine. |

Anyone who **clones** the repo can:

- **Run locally** with Docker Compose and **`.env`** — no Terraform and no access to your AWS state (see [`docs/installation.md`](../../docs/installation.md)).
- **Provision their own AWS** by following [`docs/deploy/aws-ecs.md`](../../docs/deploy/aws-ecs.md) and this README: bootstrap (or reuse patterns), create **their** **`backend.hcl`** and **`terraform.tfvars`**, then **`terraform init -backend-config=backend.hcl`** and **`apply`**. They get **their** VPC, ECR, ALB, buckets — not yours.

**Region:** `aws_region` in `terraform.tfvars` must stay the region where resources were created (**do not** switch e.g. `eu-west-1` → `us-east-1` on an existing state without a planned migration or destroy). SSM secrets and the remote state bucket must use the **same** region as the stack.

**Dev vs prod state:** one shared bucket; **separate objects** — `aira/terraform/state/development.tfstate` and `aira/terraform/state/production.tfstate` (see [`bootstrap/README.md`](bootstrap/README.md)).

**Local Docker Compose** (repo root `docker-compose.yml`) is unchanged by Terraform: API/UI ports and `NEXT_PUBLIC_API_BASE_URL` at image build time stay on your machine. **`cors_origins` / `CORS_ORIGINS` in `terraform.tfvars`** apply only to the **ECS** API task for the hosted demo (ALB + CloudFront UI).

### Capstone (frozen V1) vs Version 2 — separate remote state (required)

**Do not** let the frozen capstone stack and the evolving V2 stack share the same remote state object. Sharing one `key=` means a V2 `apply` can plan destroys or drift against resources you thought belonged to capstone — **state pollution**.

| Line | Rule |
|------|------|
| **Capstone / `capstone-v1`** | Use a **dedicated** `backend.hcl` (or env root) whose `key` is only for that line (e.g. `aira/terraform/state/capstone-v1.tfstate`). Apply Terraform only from that branch when touching this state. |
| **Version 2** | Use a **different** backend: either a **different S3 `key`** in the same bucket (e.g. `aira/terraform/state/dev-v2.tfstate`) or, for stronger isolation, a **second bootstrap** (separate S3 bucket + lock table) used only by V2. Copy modules/tfvars across as needed — **never** copy `backend.hcl` state identity from capstone. |
| **Copying code** | Duplicating `envs/dev` → `envs/dev-v2` (or similar) is fine; **each** copy must have its own `key` (and own `terraform.tfvars` / naming if resources must not collide). |

**Operational habit:** before `terraform init` / `apply`, confirm `git branch` and that `backend.hcl` matches the line you intend (capstone vs V2).

## Dev (first apply)

**Greenfield (no `:latest` image in ECR yet):** a full **`terraform apply`** can fail because the config reads **`data.aws_ecr_image`** for **`latest`**. Order: **`terraform apply -target=module.ecr`**, then from repo root **`uv run rag-build`** (or your index command), then push an image (**`./scripts/aws/push_api_to_ecr.sh dev`** with **`SKIP_TERRAFORM_APPLY=1`** or a manual **`docker build` / `docker push`** to that repo’s **`:latest`**), then **`terraform apply`** for the rest. Alternatively set **`api_desired_count = 0`** until after the first image exists, per [`docs/deploy/aws-ecs.md`](../../docs/deploy/aws-ecs.md).

```bash
cd infra/terraform/envs/dev
cp backend.hcl.example backend.hcl              # edit bucket/key/region from bootstrap outputs
cp terraform.tfvars.example terraform.tfvars   # edit: aws_region (must match backend), SSM paths
terraform init -backend-config=backend.hcl     # add -migrate-state if moving local state
terraform plan
terraform apply   # or -target=module.ecr first on greenfield (see above)
```

**SSM Parameter Store:** define secrets in `terraform.tfvars` — either `openai_api_key_ssm_parameter` (sets `OPENAI_API_KEY`) or a list `ssm_secrets` mapping **env var names** → **parameter paths** (each path starts with `/`). Create each as **SecureString** in the same region; `terraform output ssm_container_secrets` shows the full list. Details: [`docs/deploy/aws-ecs.md`](../../docs/deploy/aws-ecs.md).

**ECR + ECS rollout:** use **[Phase 11](#phase-11--push-image-and-roll-out-ecs)** below and [`docs/deploy/aws-ecs.md`](../../docs/deploy/aws-ecs.md).

**Bootstrap without a runnable image:** set `api_desired_count = 0` in `terraform.tfvars` so apply succeeds; scale up after push.

## Prod

Same flow from [`envs/prod`](envs/prod/) with stricter defaults (`alb_enable_deletion_protection`, higher `api_desired_count`, longer log retention). Tighten `alb_ingress_cidr_ipv4` when the ALB sits behind CloudFront or a known egress range.

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

## Tear down an environment

From **repository root** (interactive confirm — type `dev` or `prod`). If you are in `infra/terraform/envs/dev` or `prod`, `cd` up to the repo root first — `./scripts/...` is relative to your **current** directory.

```bash
./scripts/terraform/destroy_dev.sh
./scripts/terraform/destroy_prod.sh
```

Details, `TF_DESTROY_AUTO_APPROVE`, ALB deletion protection, and bootstrap: **[`scripts/terraform/README.md`](../../scripts/terraform/README.md)**.

