# Contributing & branch workflow

## Branches: `dev` vs `main`

| Branch | Role |
|--------|------|
| **`dev`** | Day-to-day integration — push feature commits here (or use short-lived `feature/*` branches that merge into **`dev`** via PR). |
| **`main`** | Stable line — **do not push directly.** Update only by merging a PR from **`dev`** (or a release branch) after CI is green. |

This matches a single remote that only had **`main`**: add **`dev`**, do routine work there, and promote with **`dev` → `main`** PRs.

### One-time setup (after your tree is clean)

From the repo root, with latest **`main`** checked out and your work committed:

```bash
git checkout main
git pull origin main
git checkout -b dev
git push -u origin dev
```

Then in **GitHub → Settings → Branches**:

1. **Add rule** for **`main`**: enable **Require a pull request before merging** (and optionally **Require status checks to pass**, selecting the **CI** workflow).
2. Optional: set **default branch** to **`dev`** so new clones and PRs default to integration work (**Settings → General → Default branch**). Many teams keep **default = `dev`** for this pattern.

### Ongoing flow

```text
feature work → commit → push origin dev
              → open PR dev → main when you want a release
              → merge (CI should pass on the PR)
```

**Deploy API (dev)** workflow: in Actions, choose branch **`dev`** when using **Run workflow** (dropdown “Use workflow from”). If you run it from **`main`**, the **gate** job fails on purpose — that email is expected until you re-run from **`dev`**.

---

## GitHub Actions — secrets & variables

Configure under **Settings → Secrets and variables → Actions**.

### Required for nothing (CI is green out of the box)

The **CI** workflow needs **no** secrets to run **lint**, **tests**, **Terraform validate**, **frontend build**, and **Docker build**.

### Optional repository secrets

| Secret | Used by | Purpose |
|--------|---------|---------|
| **`OPENAI_API_KEY`** | `CI` → job **eval-smoke** | If unset, that job still runs but **skips** `rag-build` / `triage-eval` (no cost). Add the secret only if you want live LLM checks in CI. |

| **`AWS_DEPLOY_ROLE_ARN`** | `Deploy API (dev)` | IAM role ARN for **OIDC**. Required **only** when you use the deploy workflow **and** have set the **DEV_\*** variables. Omit if you deploy only via **`./scripts/aws/push_api_to_ecr.sh`**. |

**Note:** GitHub does not allow **`secrets.*` inside job-level `if:`** expressions. Workflows use branch checks / variables at the job level and read secrets inside **steps** (or skip in shell) instead.

### Optional repository variables

Used only when **`AWS_DEPLOY_ROLE_ARN`** is set and you run **Deploy API (dev)**:

| Variable | Example | Purpose |
|----------|---------|---------|
| **`AWS_REGION`** | `eu-west-1` | Region for ECR + ECS calls |
| **`DEV_ECR_REPOSITORY_URL`** | `123456789012.dkr.ecr.eu-west-1.amazonaws.com/aira-dev-api` | ECR repo URI (no tag) |
| **`DEV_ECS_CLUSTER_NAME`** | *(from `terraform output`)* | ECS cluster |
| **`DEV_ECS_SERVICE_NAME`** | *(from `terraform output`)* | ECS service |

Details and IAM sketch: [`docs/deploy/ci.md`](deploy/ci.md).

### What stays *outside* GitHub

Do **not** put these in Actions secrets unless you have a very specific automation design:

- **Terraform** `terraform.tfvars`, **`backend.hcl`**, AWS access for **`terraform apply`** (use your laptop or a dedicated runner with IAM roles).
- **SSM Parameter Store** paths / API keys for ECS (already documented in [`docs/deploy/aws-ecs.md`](deploy/aws-ecs.md)).
- Root **`.env`** (local only; never commit).

---

## Local checks (before pushing)

```bash
uv sync --frozen --extra dev
uv run ruff check app tests scripts/ci
uv run pytest tests/unit tests/integration -q
```

See also [`docs/deploy/ci.md`](deploy/ci.md) for full CI parity commands.
