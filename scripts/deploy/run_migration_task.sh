#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <development|production> <workflow-run-id>" >&2
  exit 2
fi
if [[ ! "$2" =~ ^[0-9]+$ ]]; then
  echo "workflow run ID must be numeric" >&2
  exit 2
fi

case "$1" in
  development) tf_dir="infra/terraform/hosted/envs/dev" ;;
  production) tf_dir="infra/terraform/hosted/envs/prod" ;;
  *) echo "invalid environment: $1" >&2; exit 2 ;;
esac

cluster="$(terraform -chdir="$tf_dir" output -raw ecs_cluster_name)"
task_definition="$(terraform -chdir="$tf_dir" output -raw migration_task_definition_arn)"
security_group="$(terraform -chdir="$tf_dir" output -raw worker_security_group_id)"
subnets="$(terraform -chdir="$tf_dir" output -json private_application_subnet_ids)"
network_configuration="$(jq -cn \
  --argjson subnets "$subnets" \
  --arg security_group "$security_group" \
  '{awsvpcConfiguration:{subnets:$subnets,securityGroups:[$security_group],assignPublicIp:"DISABLED"}}')"

task_arn="$(aws ecs run-task \
  --cluster "$cluster" \
  --task-definition "$task_definition" \
  --launch-type FARGATE \
  --network-configuration "$network_configuration" \
  --started-by "github-actions-$2" \
  --query 'tasks[0].taskArn' \
  --output text \
  --no-cli-pager)"
if [[ -z "$task_arn" || "$task_arn" == "None" ]]; then
  echo "Migration task did not start." >&2
  exit 1
fi
echo "Migration task: $task_arn"

if ! timeout 20m aws ecs wait tasks-stopped \
  --cluster "$cluster" \
  --tasks "$task_arn"; then
  echo "Migration task did not stop within 20 minutes." >&2
  exit 1
fi

task="$(aws ecs describe-tasks --cluster "$cluster" --tasks "$task_arn" --no-cli-pager)"
exit_code="$(jq -r '.tasks[0].containers[] | select(.name == "migration") | .exitCode // -1' <<<"$task")"
stopped_reason="$(jq -r '.tasks[0].stoppedReason // "unknown"' <<<"$task")"
echo "Migration stopped: exit_code=$exit_code reason=$stopped_reason"
if [[ "$exit_code" != "0" ]]; then
  exit 1
fi
