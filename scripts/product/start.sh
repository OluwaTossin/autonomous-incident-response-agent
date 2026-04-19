#!/usr/bin/env bash
# Start the default product stack: API + Next.js static UI (see repo-root docker-compose.yml).
# Optional n8n: pass --profile automation (or set COMPOSE_PROFILES=automation).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
exec docker compose up -d --build "$@"
