#!/usr/bin/env bash
# Build Next.js static export (output: export) and publish to S3; CloudFront invalidation only if a distribution exists.
# Prereq: terraform applied in env (creates bucket; distribution optional).
#
# Usage (repo root):
#   ./scripts/aws/deploy_frontend_cdn.sh dev
#   ./scripts/aws/deploy_frontend_cdn.sh prod
#
# Bakes NEXT_PUBLIC_API_BASE_URL from Terraform alb_url for that env (override: export
# NEXT_PUBLIC_API_BASE_URL before running this script). Does not affect local Docker Compose builds.
# After first UI deploy, add triage_ui_url to cors_origins in terraform.tfvars and re-apply API stack.

set -euo pipefail

ENV_NAME="${1:-}"
if [[ "$ENV_NAME" != "dev" && "$ENV_NAME" != "prod" ]]; then
  echo "Usage: $0 dev|prod" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TF_DIR="$REPO_ROOT/infra/terraform/envs/$ENV_NAME"
FRONTEND="$REPO_ROOT/frontend"

if ! command -v terraform >/dev/null 2>&1; then
  echo "terraform not on PATH" >&2
  exit 1
fi
if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI not on PATH" >&2
  exit 1
fi

BUCKET="$(terraform -chdir="$TF_DIR" output -raw triage_ui_s3_bucket_id)"
DIST="$(terraform -chdir="$TF_DIR" output -raw triage_ui_cloudfront_distribution_id)"
REGION="$(terraform -chdir="$TF_DIR" output -raw aws_region)"
ALB_URL="$(terraform -chdir="$TF_DIR" output -raw alb_url)"
export NEXT_PUBLIC_API_BASE_URL="${NEXT_PUBLIC_API_BASE_URL:-$ALB_URL}"

echo "S3 bucket:     $BUCKET"
if [[ -n "$DIST" ]]; then
  echo "CloudFront:    $DIST"
else
  echo "CloudFront:    (none — S3 website mode; set enable_triage_ui_cloudfront = true for HTTPS demo)"
fi
echo "API (baked):   $NEXT_PUBLIC_API_BASE_URL"
if [[ "${NEXT_PUBLIC_API_BASE_URL}" != "${ALB_URL}" ]]; then
  echo "               (overridden from env; default from Terraform alb_url is $ALB_URL)"
fi
echo ""

cd "$FRONTEND"
rm -rf out .next
npm run build

aws s3 sync out/ "s3://${BUCKET}/" --delete --region "$REGION"

if [[ -n "$DIST" ]]; then
  aws cloudfront create-invalidation --distribution-id "$DIST" --paths "/*" --no-cli-pager >/dev/null
  echo "CloudFront invalidation submitted for /*"
else
  echo "Skipped CloudFront invalidation (no distribution in this env)."
fi

UI_URL="$(terraform -chdir="$TF_DIR" output -raw triage_ui_url)"
echo ""
echo "Triage UI: $UI_URL"
echo ""
echo "CORS (required for browser): add this exact URL to cors_origins in terraform.tfvars, then:"
echo "  cd $TF_DIR && terraform apply"
echo "  # wait until ECS tasks roll — CORS is read from CORS_ORIGINS on the API container"
echo "Example:"
echo "  cors_origins = \"http://localhost:3000,http://127.0.0.1:3000,$UI_URL\""
echo ""
echo "If the UI still shows CORS errors after apply: rebuild API for this env (includes OPTIONS handlers):"
echo "  ./scripts/aws/push_api_to_ecr.sh $ENV_NAME"
echo "Verify preflight:"
echo "  ./scripts/aws/verify_triage_cors_preflight.sh $ENV_NAME"
