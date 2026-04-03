#!/usr/bin/env bash
# Phase 11 — build API image (with baked .rag_index), push immutable tag + :latest to ECR,
# then terraform apply so ECS uses the digest of :latest (no manual tfvars sync).
#
# Prerequisites:
#   - Terraform applied once for the env; backend.hcl configured for remote state if used.
#   - Docker, AWS CLI, Terraform on PATH; aws configure for the same account/region as the stack.
#   - From repo root: `uv run rag-build` so `.rag_index/index.faiss` exists.
#
# Usage (repo root):
#   ./scripts/aws/push_api_to_ecr.sh dev
#   ./scripts/aws/push_api_to_ecr.sh prod
#
# Env:
#   IMAGE_TAG              — override immutable tag (default: git short SHA, else build-UTC timestamp).
#   DOCKER_BUILD_PLATFORM  — default linux/amd64 (Fargate).
#   PUSH_ONLY=1           — docker push only; no terraform / no ECS update.
#   SKIP_TERRAFORM_APPLY=1 — push only + print terraform apply hint (no apply).
#   TF_APPLY_AUTO_APPROVE=1 — pass -auto-approve to terraform apply (CI / non-interactive).
#   SKIP_ECS_ROLLOUT=1    — deprecated; same as SKIP_TERRAFORM_APPLY=1.

set -euo pipefail

ENV_NAME="${1:-}"
if [[ "$ENV_NAME" != "dev" && "$ENV_NAME" != "prod" ]]; then
  echo "Usage: $0 <dev|prod>" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TF_DIR="$REPO_ROOT/infra/terraform/envs/$ENV_NAME"
INDEX_FAISS="$REPO_ROOT/.rag_index/index.faiss"

if [[ ! -f "$INDEX_FAISS" ]]; then
  echo "Missing $INDEX_FAISS — run from repo root: uv run rag-build" >&2
  exit 1
fi

if ! command -v terraform >/dev/null 2>&1; then
  echo "terraform not found on PATH" >&2
  exit 1
fi
if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI not found on PATH" >&2
  exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found on PATH" >&2
  exit 1
fi

default_tag() {
  if git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    local sha
    sha="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || true)"
    if [[ -n "$sha" ]]; then
      echo "$sha"
      return
    fi
  fi
  echo "build-$(date -u +%Y%m%d%H%M%S)"
}

IMAGE_TAG="${IMAGE_TAG:-$(default_tag)}"
# Docker tag: allow a-z A-Z 0-9 _ . -
if [[ ! "$IMAGE_TAG" =~ ^[a-zA-Z0-9._-]+$ ]]; then
  echo "IMAGE_TAG must match [a-zA-Z0-9._-]+ (got: $IMAGE_TAG)" >&2
  exit 1
fi

ECR_URL="$(terraform -chdir="$TF_DIR" output -raw ecr_repository_url)"
CLUSTER="$(terraform -chdir="$TF_DIR" output -raw ecs_cluster_name)"
SERVICE="$(terraform -chdir="$TF_DIR" output -raw ecs_service_name)"
REGION="$(terraform -chdir="$TF_DIR" output -raw aws_region)"

ECR_HOST="${ECR_URL%%/*}"
PLATFORM="${DOCKER_BUILD_PLATFORM:-linux/amd64}"

echo "ECR: $ECR_URL"
echo "Cluster: $CLUSTER  Service: $SERVICE  Region: $REGION  Platform: $PLATFORM  Tags: $IMAGE_TAG + latest"

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ECR_HOST"

docker build --platform "$PLATFORM" -f "$REPO_ROOT/Dockerfile" -t "aira-api:${ENV_NAME}" "$REPO_ROOT"
docker tag "aira-api:${ENV_NAME}" "${ECR_URL}:${IMAGE_TAG}"
docker push "${ECR_URL}:${IMAGE_TAG}"

docker tag "aira-api:${ENV_NAME}" "${ECR_URL}:latest"
docker push "${ECR_URL}:latest"

if [[ "${PUSH_ONLY:-}" == "1" ]]; then
  echo "PUSH_ONLY=1 — skipping Terraform and ECS rollout."
  exit 0
fi

if [[ "${SKIP_TERRAFORM_APPLY:-}" == "1" || "${SKIP_ECS_ROLLOUT:-}" == "1" ]]; then
  echo "Skipping terraform apply. Run when ready (resolves digest of :latest):"
  printf '  terraform -chdir="%s" apply\n' "$TF_DIR"
  exit 0
fi

echo "Running terraform apply (ECS will use digest of :latest) …"
if [[ "${TF_APPLY_AUTO_APPROVE:-}" == "1" ]]; then
  terraform -chdir="$TF_DIR" apply -auto-approve
else
  terraform -chdir="$TF_DIR" apply
fi

printf 'Done. ALB: %s\n' "$(terraform -chdir="$TF_DIR" output -raw alb_url)"
printf 'Pinned image: %s\n' "$(terraform -chdir="$TF_DIR" output -raw ecr_image_uri)"
