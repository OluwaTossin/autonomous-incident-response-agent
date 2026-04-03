# Deploy API to AWS (Phase 11 — ECS Fargate + ALB)

This path assumes **Phase 10** is applied: ECR repository, ECS cluster/service, ALB, and **AWS Systems Manager Parameter Store** for sensitive env vars. **n8n** is not part of this Terraform stack; only the triage API is deployed here.

### Secrets in Parameter Store

Terraform wires **ECS container secrets** so each value lives in **SSM** as a **SecureString** and is injected at task start as a normal **environment variable** (never stored in the task definition JSON as plain text).

| Terraform input | Purpose |
|-----------------|--------|
| `openai_api_key_ssm_parameter` | Shorthand: maps **`OPENAI_API_KEY`** → one parameter path (e.g. `/aira/dev/openai_api_key`). |
| `ssm_secrets` | List of `{ env_name, parameter_name }` for **any** secret the app reads from the environment (`OPENAI_API_KEY`, `OPENROUTER_API_KEY`, etc.). |

Rules:

- **`parameter_name`** must be the full path starting with **`/`** (Standard tier is fine for typical API keys).
- Do **not** set the same **`env_name`** twice (including `OPENAI_API_KEY` in both the shorthand and `ssm_secrets`); `terraform plan` will fail the uniqueness check.
- The **task execution role** is granted **`ssm:GetParameter`** / **`GetParameters`** only on the ARNs Terraform builds from your list.

After apply, **`terraform output ssm_container_secrets`** lists each **`environment_variable`**, **`parameter_name`**, and **`arn`** you must create in SSM.

If **no** parameters are configured, `terraform apply` still succeeds, but **`POST /triage`** will fail without **`OPENAI_API_KEY`** (while **`GET /health`** may still return 200).

## 1. One-time: Terraform

From [`infra/terraform/envs/dev`](../../infra/terraform/envs/dev) or [`envs/prod`](../../infra/terraform/envs/prod):

```bash
cp terraform.tfvars.example terraform.tfvars
# Set aws_region, openai_api_key_ssm_parameter and/or ssm_secrets
terraform init && terraform apply
```

Create each parameter in the **same region** as the stack (names must match `terraform.tfvars`):

```bash
REGION=eu-west-1   # example: match var.aws_region
aws ssm put-parameter --region "$REGION" --name /aira/dev/openai_api_key --type SecureString --value "$(printf %s "$OPENAI_API_KEY")"
```

Then **`terraform apply`** (if you changed tfvars only). To ship a **new container image**, use the push script: it pushes an **immutable tag** (default **git short SHA**) **and** **`:latest`**, then runs **`terraform apply`**. Terraform reads the **digest** of **`:latest`** and pins **`repository@digest`** on the ECS task definition — no **`api_image_tag`** in **`terraform.tfvars`**.

```bash
./scripts/aws/push_api_to_ecr.sh dev
# CI / non-interactive: TF_APPLY_AUTO_APPROVE=1 ./scripts/aws/push_api_to_ecr.sh dev
# Docker-only: PUSH_ONLY=1 ./scripts/aws/push_api_to_ecr.sh dev
```

After apply, **`terraform output ecr_image_digest`** / **`ecr_image_uri`** show what ECS is running.

## 2. Build the RAG index on the host

The Docker image **bakes** `.rag_index/` (FAISS + chunk metadata). From **repo root**:

```bash
uv run rag-build
```

## 3. Push image and roll out ECS

Use the same AWS account/region as Terraform. On **Apple Silicon**, the script defaults to **`linux/amd64`** so Fargate can run the image.

```bash
./scripts/aws/push_api_to_ecr.sh dev
# or: ./scripts/aws/push_api_to_ecr.sh prod
```

Environment knobs:

| Variable | Effect |
|----------|--------|
| `IMAGE_TAG` | Override immutable tag (default: **git short SHA**, else `build-UTCtimestamp`); **`:latest`** is always updated too. |
| `TF_APPLY_AUTO_APPROVE=1` | Non-interactive `terraform apply` after push. |
| `PUSH_ONLY=1` | Build/push only; run **`terraform apply`** yourself when you want ECS to pick up the new **`:latest`** digest. |
| `SKIP_TERRAFORM_APPLY=1` | Push only + prints **`terraform apply`** hint (legacy **`SKIP_ECS_ROLLOUT=1`** alias). |
| `DOCKER_BUILD_PLATFORM` | Default `linux/amd64`; set `linux/arm64` only if Fargate uses ARM. |

## 4. Smoke test

After tasks are **running** and the target group shows **healthy** (often 1–2 minutes after the image exists in ECR):

From **repo root** (or use `terraform output -raw alb_url` inside `envs/dev` / `envs/prod` without `-chdir`):

```bash
ALB="$(terraform -chdir=infra/terraform/envs/dev output -raw alb_url)"
curl -sS "${ALB}/health"
```

**zsh:** printing `terraform output -raw alb_url` alone may show a trailing **`%`** on the next line. That is zsh’s marker for “output had no newline”; it is **not** part of the URL. Use `echo "$ALB"` or the `ALB="$(…)"` pattern above.

Then `POST /triage` with a sample payload (see root `README.md`).

## 5. Dev vs prod

Use **`dev`** or **`prod`** as the script argument so Terraform outputs resolve to the correct **ECR repository**, **cluster**, and **service**. Keep separate **SSM** parameters (e.g. `/aira/dev/...` vs `/aira/prod/...`).

### Prod (first time)

1. Reuse the same S3/DynamoDB backend from [`bootstrap`](../../infra/terraform/bootstrap): create **`infra/terraform/envs/prod/backend.hcl`** from [`backend.hcl.example`](../../infra/terraform/envs/prod/backend.hcl.example) — same `bucket` / `dynamodb_table` / `region` as dev, but **`key = "aira/terraform/state/production.tfstate"`** (dev uses **`…/development.tfstate`**; separate remote state objects).
2. `cd infra/terraform/envs/prod` → `terraform init -backend-config=backend.hcl` → copy **`terraform.tfvars.example`** → **`terraform.tfvars`** (region, **`openai_api_key_ssm_parameter = "/aira/prod/openai_api_key"`**, etc.).
3. Create prod SSM parameters in that region (same pattern as dev).
4. **Greenfield ECR / no `:latest` yet:** run **`terraform apply -target=module.ecr`** (creates the repo), then **`./scripts/aws/push_api_to_ecr.sh prod`** with **`SKIP_TERRAFORM_APPLY=1`** or **`PUSH_ONLY=1`** so an image with **`:latest`** exists, then **`terraform apply`**. Alternatively set **`api_desired_count = 0`** until after the first push + full apply.
5. From repo root: **`./scripts/aws/push_api_to_ecr.sh prod`** for routine releases (pushes tags + **`:latest`**, then applies Terraform).

## 6. Operational notes

- **TLS:** the ALB listener is HTTP **:80** in the lean module. Add HTTPS (ACM + listener) before serious production use.
- **Triage audit JSONL:** the container has no bind-mounted `data/` volume; audit files are ephemeral unless you add EFS or ship logs elsewhere. Consider `TRIAGE_AUDIT_DISABLE=1` in `extra_task_environment` in `terraform.tfvars` if you want to avoid writing under `/app/data` on Fargate.
- **Re-deploy after index changes:** run `rag-build`, then `./scripts/aws/push_api_to_ecr.sh <env>` again.
- **Phase 12 — hosted triage UI:** Next.js static export under [`frontend/`](../../frontend/) → S3 (optional CloudFront). After `terraform apply`, run **`./scripts/aws/deploy_frontend_cdn.sh <env>`** from repo root. Copy **`terraform output -raw triage_ui_url`** into **`cors_origins`** in **`terraform.tfvars`**, **`terraform apply`**, then rebuild/push the API image so the task picks up **`CORS_ORIGINS`**. See [`frontend/README.md`](../../frontend/README.md).

## 7. Troubleshooting (from real deploys)

| Symptom | Cause | What to do |
|--------|--------|------------|
| `CannotPullContainerError` … `not found` | No **`:latest`** (or digest) in ECR yet | Push with **`./scripts/aws/push_api_to_ecr.sh <env>`** (or at least push **`:latest`**), then **`terraform apply`**. |
| `runningCount: 0`, many failed tasks | Same as above, or bad image / crash loop | After push, check **CloudWatch Logs** → log group from `terraform output cloudwatch_log_group`. |
| `GET /health` OK, `POST /triage` errors on API key | `openai_api_key_ssm_parameter` empty or SSM missing / wrong name | Set tfvars, create SSM SecureString, `terraform apply`, force new deployment. |
| 502 from ALB briefly | Target warming up | Wait; ECS **health check grace period** (default 90s, set in Terraform) reduces premature draining. |
| Browser UI: CORS / OPTIONS **405** on **`POST /triage`** | UI origin not in **`cors_origins`** or stale API image | Set **`cors_origins`** to include the exact **`triage_ui_url`** (and local dev origins if needed), **`terraform apply`**, then **`./scripts/aws/push_api_to_ecr.sh <env>`**. Verify: **`./scripts/aws/verify_triage_cors_preflight.sh <env>`**. |
| UI loads but API calls fail cross-origin | Mismatched scheme/host vs **`CORS_ORIGINS`** | Origins must match the browser bar exactly (e.g. `http://` vs `https://`, trailing slash usually omitted). |
