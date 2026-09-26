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

mapfile -t secret_arns < <(terraform -chdir="$tf_dir" output -json runtime_secret_arns | jq -r '.[]')
if [[ ${#secret_arns[@]} -eq 0 ]]; then
  echo "No runtime secret containers were returned by Terraform." >&2
  exit 1
fi

for secret_arn in "${secret_arns[@]}"; do
  current_versions="$(aws secretsmanager list-secret-version-ids \
    --secret-id "$secret_arn" \
    --query 'length(Versions[?contains(VersionStages, `AWSCURRENT`)])' \
    --output text \
    --no-cli-pager)"
  if [[ "$current_versions" != "1" ]]; then
    echo "Runtime secret has no unique AWSCURRENT version: $secret_arn" >&2
    exit 1
  fi
done

echo "Verified ${#secret_arns[@]} populated runtime secret containers without reading values."
