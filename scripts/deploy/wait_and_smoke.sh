#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <development|production>" >&2
  exit 2
fi

case "$1" in
  development) tf_dir="infra/terraform/hosted/envs/dev" ;;
  production) tf_dir="infra/terraform/hosted/envs/prod" ;;
  *) echo "invalid environment: $1" >&2; exit 2 ;;
esac

cluster="$(terraform -chdir="$tf_dir" output -raw ecs_cluster_name)"
mapfile -t services < <(terraform -chdir="$tf_dir" output -json ecs_service_names | jq -r '.[]')
if ! timeout 20m aws ecs wait services-stable \
  --cluster "$cluster" \
  --services "${services[@]}"; then
  echo "ECS services did not stabilize within 20 minutes." >&2
  aws ecs describe-services --cluster "$cluster" --services "${services[@]}" \
    --query 'services[].{service:serviceName,desired:desiredCount,running:runningCount,pending:pendingCount,events:events[0:3]}' \
    --no-cli-pager
  exit 1
fi

deployment_state="$(aws ecs describe-services \
  --cluster "$cluster" \
  --services "${services[@]}" \
  --query 'services[].{service:serviceName,taskDefinition:taskDefinition,desired:desiredCount,running:runningCount}' \
  --output json \
  --no-cli-pager)"

api_url="$(terraform -chdir="$tf_dir" output -raw api_url)"
web_url="$(terraform -chdir="$tf_dir" output -raw web_url)"
for endpoint in "$api_url/healthz" "$api_url/readyz" "$web_url/healthz"; do
  success=0
  for _ in {1..12}; do
    if curl --fail --silent --show-error --max-time 10 "$endpoint" >/dev/null; then
      success=1
      break
    fi
    sleep 10
  done
  if [[ "$success" != "1" ]]; then
    echo "Smoke check failed: $endpoint" >&2
    exit 1
  fi
done

echo "ECS stability and unauthenticated health/readiness smoke checks passed."
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo "### ECS rollout"
    jq -r '.[] | "- \(.service): `\(.taskDefinition)` (\(.running)/\(.desired) running)"' \
      <<<"$deployment_state"
    echo "- ALB health endpoints: web \`/healthz\`, API \`/healthz\`, and API \`/readyz\` passed"
  } >> "$GITHUB_STEP_SUMMARY"
fi
