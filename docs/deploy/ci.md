# CI/CD (Phase 14 — GitHub Actions)

## Secrets & variables (quick list)

| Where | Name | Required? |
|-------|------|-----------|
| **Secret** | `OPENAI_API_KEY` | No — enables **eval-smoke** (live LLM + cost) |
| **Secret** | `AWS_DEPLOY_ROLE_ARN` | No — enables **Deploy API (dev)** (OIDC) |
| **Variable** | `AWS_REGION` | Only with deploy workflow |
| **Variable** | `DEV_ECR_REPOSITORY_URL` | Only with deploy workflow |
| **Variable** | `DEV_ECS_CLUSTER_NAME` | Only with deploy workflow |
| **Variable** | `DEV_ECS_SERVICE_NAME` | Only with deploy workflow |

Branching (**`dev`** vs **`main`**) and protecting **`main`**: see **[`docs/contributing.md`](../contributing.md)**.

---

## Continuous integration (`/.github/workflows/ci.yml`)

Runs on **push** to **`dev`** or **`main`**, and on **pull requests** targeting **`dev`** or **`main`**:

| Job | What it does |
|-----|----------------|
| **lint** | `uv sync` + `ruff check` on `app/`, `tests/`, `scripts/ci/` |
| **terraform** | `terraform fmt -check` on `infra/terraform`, then `init -backend=false` + `validate` in `envs/dev` |
| **test** | `pytest tests/unit tests/integration` (`ENABLE_GRADIO_UI=0`) |
| **frontend** | `npm ci` + `npm run build` in `frontend/` (`NEXT_PUBLIC_API_BASE_URL` placeholder for static export) |
| **docker** | `scripts/ci/stub_rag_index.py` (no OpenAI) then `docker build` — same `Dockerfile` as production |
| **eval-smoke** | *Optional.* Runs only if repository secret **`OPENAI_API_KEY`** is set: `uv run rag-build` then `uv run triage-eval --limit 3` |

Fork PRs and repos without **`OPENAI_API_KEY`** skip **eval-smoke**; the rest of CI still gates merges.

### Optional: live eval in CI

1. Repo **Settings → Secrets and variables → Actions → New repository secret**  
2. Name: **`OPENAI_API_KEY`**  
3. Re-run workflows; **eval-smoke** will build a real index and run three gold cases (costs a small amount of API usage per run).

### Local parity

```bash
uv sync --frozen --extra dev
uv run ruff check app tests scripts/ci
uv run pytest tests/unit tests/integration -q
terraform fmt -check -recursive infra/terraform
(cd infra/terraform/envs/dev && rm -rf .terraform && terraform init -backend=false -lockfile=readonly && terraform validate)
uv run python scripts/ci/stub_rag_index.py && docker build -f Dockerfile -t aira-api:local .
```

**Terraform lock file:** CI uses **Terraform 1.9.4** (pinned in the workflow). The committed **`.terraform.lock.hcl`** must include **multiple `h1:`** hashes (registry signing) or Linux **`terraform validate`** can fail with “cached package does not match checksums”. Refresh from any env root:

`terraform init -backend=false` then commit changes, or run `terraform providers lock -platform=linux_amd64 -platform=darwin_amd64 -platform=darwin_arm64` with the same Terraform version as CI.

## Manual deploy to dev (`/.github/workflows/deploy-dev.yml`)

**Workflow dispatch only** — does **not** run Terraform. It builds the API image (stub RAG index), pushes **`:${{ github.sha }}`** and **`:latest`** to **ECR**, then **`ecs update-service --force-new-deployment`** so Fargate pulls the new digest.

### When to use

- You want a CI button instead of `./scripts/aws/push_api_to_ecr.sh dev` from a laptop.  
- Your task definition already references the ECR repo **`latest`** (or you accept that ECS uses the repo’s current **`latest`** digest after push).

For **Terraform-managed** image digests and full parity with [`docs/deploy/aws-ecs.md`](aws-ecs.md), keep using **`./scripts/aws/push_api_to_ecr.sh`** (it runs **`terraform apply`** after push).

### Setup (repository)

| Kind | Name | Example / notes |
|------|------|-----------------|
| **Secret** | `AWS_DEPLOY_ROLE_ARN` | IAM role ARN trusted by GitHub OIDC for this repo |
| **Variable** | `AWS_REGION` | e.g. `eu-west-1` |
| **Variable** | `DEV_ECR_REPOSITORY_URL` | Full URI without tag: `123456789012.dkr.ecr.eu-west-1.amazonaws.com/aira-dev-api` |
| **Variable** | `DEV_ECS_CLUSTER_NAME` | ECS cluster name from Terraform output |
| **Variable** | `DEV_ECS_SERVICE_NAME` | ECS service name from Terraform output |

If **`DEV_ECR_REPOSITORY_URL`** or **`AWS_DEPLOY_ROLE_ARN`** is missing, the deploy job is **skipped** (workflow still succeeds).

### IAM (outline)

Trust policy: `sts:AssumeRoleWithWebIdentity` for `token.actions.githubusercontent.com`, **sub** / **aud** conditioned to your repo and (optionally) environment.

Permissions (tighten ARNs to your account):

- **ECR:** `GetAuthorizationToken`; `BatchCheckLayerAvailability`, `CompleteLayerUpload`, `InitiateLayerUpload`, `PutImage`, `UploadLayerPart` on the dev API repository  
- **ECS:** `UpdateService`, `DescribeServices` on the dev cluster/service  

### Eval CLI: subset flag

```bash
uv run triage-eval --limit 5
```

Runs at most **N** cases from the gold file (see [`data/eval/README.md`](../../data/eval/README.md)).
