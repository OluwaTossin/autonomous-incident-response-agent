#!/usr/bin/env bash
# Block gate E: fail if forbidden secret markers appear in the static export tree.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${ROOT}/frontend/out"
if [[ ! -d "${OUT}" ]]; then
  echo "Expected ${OUT} — run: (cd \"${ROOT}/frontend\" && npm ci && npm run build)" >&2
  exit 1
fi
# Literal env names that must not appear in shipped assets (avoid accidental secret docs in JS).
if grep -RIn --binary-files=without-match -E 'ADMIN_API_KEY|NEXT_PUBLIC_ADMIN_API_KEY' "${OUT}" 2>/dev/null; then
  echo "verify-frontend-bundle: forbidden pattern in ${OUT}" >&2
  exit 1
fi
echo "verify-frontend-bundle: OK (${OUT})"
