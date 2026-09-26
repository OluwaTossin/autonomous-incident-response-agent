#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tmp="${TMPDIR:-/tmp}/aira-security"
mkdir -p "$tmp"
cd "$root"

uv export --frozen --no-dev --extra hosted --no-emit-project \
  --format requirements-txt --output-file "$tmp/requirements.txt" >/dev/null
uvx pip-audit==2.10.1 --disable-pip --no-deps -r "$tmp/requirements.txt"
uvx bandit==1.9.4 -q -r app

(cd web && npm audit --omit=dev)
(cd frontend && npm audit --omit=dev)

uvx checkov==3.3.19 -d infra/terraform/hosted --framework terraform --compact --soft-fail

for tool in gitleaks trivy syft; do
  command -v "$tool" >/dev/null || {
    echo "Required native scanner is missing: $tool" >&2
    exit 2
  }
done
gitleaks detect --source . --redact --exit-code 1
trivy fs --scanners vuln,secret --severity HIGH,CRITICAL --exit-code 1 .
trivy config --severity HIGH,CRITICAL --exit-code 0 infra/terraform/hosted
syft dir:. -o cyclonedx-json="$tmp/aira-sbom.cdx.json"

echo "Temporary reports: $tmp"
