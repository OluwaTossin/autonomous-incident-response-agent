#!/usr/bin/env bash
# End-to-end check: health → POST /triage (RAG + LangGraph) → n8n webhook.
#
# Usage (repo root, API reachable from this machine):
#   ./scripts/e2e_stack_check.sh
#   API_BASE=http://127.0.0.1:8000 ./scripts/e2e_stack_check.sh   # if API is host uvicorn on :8000
#
# Env:
#   API_BASE      default http://127.0.0.1:8000
#   N8N_BASE      default http://127.0.0.1:5678
#   SKIP_TRIAGE=1 skip live LLM call (health + n8n only)
#   SKIP_N8N=1    skip webhook call (health + triage only; use when Compose runs without --profile automation)
#   STRICT_RAG_EVIDENCE=1  require ≥1 evidence source under data/ (stricter)
#   API_KEY       when set, sent as x-api-key on POST /triage (must match server API_KEY)
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_BASE="${API_BASE:-http://127.0.0.1:18080}"
N8N_BASE="${N8N_BASE:-http://127.0.0.1:5678}"
SKIP_TRIAGE="${SKIP_TRIAGE:-0}"
SKIP_N8N="${SKIP_N8N:-0}"
STRICT_RAG_EVIDENCE="${STRICT_RAG_EVIDENCE:-0}"

API_KEY_HDR=()
if [[ -n "${API_KEY:-}" ]]; then
  API_KEY_HDR=(-H "x-api-key: ${API_KEY}")
fi

echo "== 1) Health: GET ${API_BASE}/health"
curl -fsS "${API_BASE}/health" >/dev/null
echo "    OK"

if [[ "${SKIP_TRIAGE}" != "1" ]]; then
  export STRICT_RAG_EVIDENCE
  echo "== 2) Triage: POST ${API_BASE}/triage (OpenAI + FAISS; may take 15–60s)"
  PAYLOAD="${ROOT}/examples/sample_incident_payload.json"
  if [[ ! -f "${PAYLOAD}" ]]; then
    echo "    ERROR: missing ${PAYLOAD}" >&2
    exit 1
  fi
  curl -fsS -X POST "${API_BASE}/triage" \
    -H "Content-Type: application/json" \
    "${API_KEY_HDR[@]}" \
    -d @"${PAYLOAD}" \
    | python3 -c "
import json, os, sys
d = json.load(sys.stdin)
err = d.get('error') or d.get('detail')
if err:
    print('    ERROR: triage returned error:', err, file=sys.stderr)
    sys.exit(1)
assert d.get('triage_id'), 'missing triage_id'
assert d.get('severity'), 'missing severity'
assert d.get('likely_root_cause'), 'missing likely_root_cause'
acts = d.get('recommended_actions')
assert isinstance(acts, list) and len(acts) >= 1, 'missing recommended_actions'
ev = d.get('evidence') or []
assert len(ev) >= 1, 'missing evidence (expected merged retrieval/LLM citations)'
if os.environ.get('STRICT_RAG_EVIDENCE') == '1':
    blob = ' '.join(str(e.get('source', '')).lower() for e in ev if isinstance(e, dict))
    assert 'data/' in blob, 'STRICT_RAG_EVIDENCE: no evidence source under data/'
print('    OK  triage_id=', d['triage_id'], ' severity=', d['severity'], sep='')
"
else
  echo "== 2) Triage skipped (SKIP_TRIAGE=1)"
fi

if [[ "${SKIP_N8N}" != "1" ]]; then
  echo "== 3) n8n: POST ${N8N_BASE}/webhook/ticket-creation (activate workflow in UI first)"
  # Triage-shaped JSON; n8n exposes this as \$json.body.*
  BODY='{"escalate":true,"incident_summary":"E2E stack check","recommended_actions":["Acknowledge"],"severity":"HIGH","likely_root_cause":"Synthetic","confidence":0.5,"evidence":[],"timeline":[]}'
  N8N_OUT="$(mktemp)"
  trap "rm -f \"${N8N_OUT}\"" EXIT
  CODE=$(curl -sS -o "${N8N_OUT}" -w "%{http_code}" -X POST "${N8N_BASE}/webhook/ticket-creation" \
    -H "Content-Type: application/json" \
    -d "${BODY}" || true)
  if [[ "${CODE}" != "200" ]]; then
    echo "    ERROR: n8n HTTP ${CODE} (import + activate incident-ticket-creation?)" >&2
    cat "${N8N_OUT}" 2>/dev/null || true
    exit 1
  fi
  python3 -c "import json,sys; d=json.load(open(sys.argv[1])); assert d.get('ok') is True, d" "${N8N_OUT}"
  echo "    OK  $(head -c 220 "${N8N_OUT}")"
else
  echo "== 3) n8n skipped (SKIP_N8N=1)"
fi

echo "== All checks passed."
