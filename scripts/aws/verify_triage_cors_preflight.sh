#!/usr/bin/env bash
# OPTIONS preflight check for Phase 12 triage UI → API (same probe the browser runs).
#
# Usage (repo root):
#   ./scripts/aws/verify_triage_cors_preflight.sh dev
#   ./scripts/aws/verify_triage_cors_preflight.sh prod
#
# Expect HTTP 200 (or 204) and access-control-allow-origin matching terraform triage_ui_url.
# If you see 400/405 or no ACAO: fix cors_origins + terraform apply, and ensure the API image
# includes current app/api/main.py CORS (./scripts/aws/push_api_to_ecr.sh <env>).

set -euo pipefail

ENV_NAME="${1:-}"
if [[ "$ENV_NAME" != "dev" && "$ENV_NAME" != "prod" ]]; then
  echo "Usage: $0 dev|prod" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TF_DIR="$REPO_ROOT/infra/terraform/envs/$ENV_NAME"

if ! command -v terraform >/dev/null 2>&1; then
  echo "terraform not on PATH" >&2
  exit 1
fi

ORIGIN="$(terraform -chdir="$TF_DIR" output -raw triage_ui_url)"
ALB="$(terraform -chdir="$TF_DIR" output -raw alb_url)"

echo "Origin (triage_ui_url): $ORIGIN"
echo "OPTIONS target:         ${ALB}/triage"
echo ""

curl -sS -D - -o /dev/null -X OPTIONS "${ALB}/triage" \
  -H "Origin: ${ORIGIN}" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type" || true

echo ""
