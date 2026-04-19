#!/usr/bin/env bash
# Rebuild the FAISS index for the active workspace (host paths; run before or after Compose).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
WS="${WORKSPACE_ID:-default}"
exec uv run product-build-index --workspace "$WS" "$@"
