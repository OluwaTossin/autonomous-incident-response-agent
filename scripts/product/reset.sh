#!/usr/bin/env bash
# Destructive: delete generated FAISS files under workspaces/<WORKSPACE_ID>/index/ (not corpus data).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WS="${WORKSPACE_ID:-default}"
TARGET="${ROOT}/workspaces/${WS}/index"

echo "This will remove generated index files under:"
echo "  ${TARGET}"
echo "Corpus under workspaces/${WS}/data/ is not touched."
read -r -p 'Type DELETE to confirm: ' ans
if [[ "${ans}" != "DELETE" ]]; then
  echo "Aborted."
  exit 1
fi

if [[ ! -d "${TARGET}" ]]; then
  echo "Nothing to do (directory missing): ${TARGET}"
  exit 0
fi

find "${TARGET}" -mindepth 1 -delete
echo "Done. Rebuild with: ./scripts/product/rebuild-index.sh"
