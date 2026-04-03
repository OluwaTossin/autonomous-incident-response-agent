#!/usr/bin/env bash
# Measure wall time for POST /triage (warm-ish repeated calls; includes LLM + RAG).
#
# Usage:
#   ./scripts/benchmark_triage_latency.sh [N] [payload.json]
# Env:
#   API_BASE  default http://127.0.0.1:18080
#   N         default 5 (overrides first arg)
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_BASE="${API_BASE:-http://127.0.0.1:18080}"
RUNS="${1:-${N:-5}}"
PAYLOAD="${2:-${ROOT}/examples/sample_incident_payload.json}"

if [[ ! -f "${PAYLOAD}" ]]; then
  echo "Missing payload: ${PAYLOAD}" >&2
  exit 1
fi

echo "API_BASE=${API_BASE}  runs=${RUNS}  payload=${PAYLOAD}"
TIMES_FILE="$(mktemp)"
trap 'rm -f "${TIMES_FILE}"' EXIT

for _ in $(seq 1 "${RUNS}"); do
  curl -sS -o /dev/null -w "%{time_total}\n" -X POST "${API_BASE}/triage" \
    -H "Content-Type: application/json" \
    -d @"${PAYLOAD}" >>"${TIMES_FILE}" || exit 1
done

python3 <<PY
import math
import statistics
import sys
path = "${TIMES_FILE}"
xs = [float(line.strip()) for line in open(path) if line.strip()]
if not xs:
    print("no samples", file=sys.stderr)
    sys.exit(1)
s = sorted(xs)
# Upper-tail index; coarse for tiny n, fine for smoke benchmarks
p95 = s[min(len(s) - 1, max(0, math.ceil(0.95 * len(s)) - 1))]
print(f"n={len(xs)}  min_s={min(xs):.3f}  max_s={max(xs):.3f}  mean_s={statistics.mean(xs):.3f}  p95_s={p95:.3f}")
PY
