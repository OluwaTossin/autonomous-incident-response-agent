# Phase 6 — n8n execution layer

Local **[n8n](https://n8n.io/)** workflows that react to **triage-shaped JSON** (same structure as `POST /triage` responses). They call your FastAPI app for a **mock Jira** create and an optional **workflow event log**.

## Prerequisites

1. **FastAPI** reachable from n8n:
   - **Phase 6 (this file):** API on the host (`uv run serve-api`, default `http://127.0.0.1:8000`).
   - **Phase 9 (full stack):** use repo-root **`docker compose up`** — n8n gets **`TRIAGE_API_BASE=http://api:8000`** automatically; no `host.docker.internal` needed.
2. **Docker** (for n8n)
3. Optional: **Slack Incoming Webhook** — in the **repository root** `.env` (same file as API keys; **gitignored**), set:
   ```env
   SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/PATH
   ```
   Do **not** put the real URL in `.env.example` or commit it. When you run `docker compose -f docker-compose.n8n.yml up` from the repo root, Compose injects that value into the n8n container as `$env.SLACK_WEBHOOK_URL`. After changing `.env`, recreate: `docker compose -f docker-compose.n8n.yml up -d --force-recreate`.

## Start n8n

From the **repository root**:

```bash
docker compose -f docker-compose.n8n.yml up -d
```

Open **http://localhost:5678**, create an owner account (first visit), then **Import** → choose:

| File | Webhook test path (after activate) |
|------|--------------------------------------|
| [`incident-triage-escalation.json`](incident-triage-escalation.json) | `POST http://localhost:5678/webhook/triage-escalation` |
| [`incident-ticket-creation.json`](incident-ticket-creation.json) | `POST http://localhost:5678/webhook/ticket-creation` |
| [`incident-triage-feedback.json`](incident-triage-feedback.json) | `POST http://localhost:5678/webhook/triage-feedback` |

**Activate** each workflow (toggle in n8n UI) so webhooks listen.

**Stack E2E:** from the repo root, with the API reachable and **`incident-ticket-creation` active**, run [`scripts/e2e_stack_check.sh`](../scripts/e2e_stack_check.sh) (set `API_BASE` if the API is not on `:8000`).

### Docker → host API

Compose sets `TRIAGE_API_BASE` default to `http://host.docker.internal:8000` and `extra_hosts: host.docker.internal:host-gateway` (Linux-friendly). If the API is elsewhere, export before `up`:

```bash
export TRIAGE_API_BASE=http://host.docker.internal:8000
docker compose -f docker-compose.n8n.yml up -d
```

## Workflow behaviour

### `incident-triage-escalation`

1. **Webhook** accepts JSON in the **HTTP body** (same shape as `POST /triage` returns). n8n exposes that payload as **`$json.body`** in expressions — the workflows use `body.severity`, `body.confidence`, etc.
2. If **`body.severity !== "CRITICAL"`** — respond `action: no_notification`.
3. If **CRITICAL**, **confidence tiers** (numeric `body.confidence`, missing treated as `0`):
   - **`confidence > 0.85`** — **Build Slack payload** (Code node) → rich Slack attachment (service, likely root cause, confidence, actions, evidence summary) → **Notify Slack** → **Workflow log** (`tier: high_confidence`) → respond `action: slack_and_page`, `tier: high` (wire PagerDuty/Opsgenie on this branch if you use them).
   - **`0.6 ≤ confidence ≤ 0.85`** — same Slack formatting → **Slack only** (no workflow log) → respond `action: slack_only`, `tier: medium`.
   - **`< 0.6`** — **Workflow log** only (`tier: log_review`) → respond `action: log_review`, `tier: low`.

If `SLACK_WEBHOOK_URL` is empty, branches that post to Slack fail at the HTTP node — set a real webhook or adjust the workflow in the UI.

### `incident-triage-feedback`

Optional follow-up: **Webhook** forwards the POST body to **`POST {TRIAGE_API_BASE}/n8n/triage-feedback`**, which appends one line to **`data/logs/triage_feedback.jsonl`** (gitignored). Include **`triage_id`** (UUID from `POST /triage`) so the row joins to **`triage_outputs.jsonl`**. Also send `diagnosis_correct`, `actions_useful`, `notes`, and optional `triage_snapshot` for eval / tuning. Each logged line has top-level `triage_id` plus the full `feedback` object. Env: `N8N_TRIAGE_FEEDBACK_DISABLE`, `N8N_TRIAGE_FEEDBACK_JSONL`.

### `incident-ticket-creation`

1. **Webhook** accepts triage-shaped JSON in the HTTP body (available as **`$json.body`**).
2. If **`body.escalate === true`** (boolean):
   - **Mock Jira create** — `POST {TRIAGE_API_BASE}/n8n/mock-jira/issue` with summary + description derived from triage.
3. **Respond** — includes mock `ticket` key or `not_escalated`.

## Test with curl

POST the **triage JSON** as the request body (no extra wrapper — n8n still maps it to **`$json.body`** internally):

```bash
# Not critical → no Slack branch
curl -s -X POST http://localhost:5678/webhook/triage-escalation \
  -H "Content-Type: application/json" \
  -d '{"severity":"HIGH","incident_summary":"test","likely_root_cause":"x","recommended_actions":["a"],"escalate":false,"confidence":0.5,"evidence":[],"timeline":[]}'

# Escalate path → mock Jira
curl -s -X POST http://localhost:5678/webhook/ticket-creation \
  -H "Content-Type: application/json" \
  -d '{"escalate":true,"incident_summary":"Outage","recommended_actions":["page"],"severity":"HIGH","likely_root_cause":"x","confidence":0.5,"evidence":[],"timeline":[]}'
```

To exercise **CRITICAL** tiers, set `"severity":"CRITICAL"` and vary `confidence` (e.g. `0.9` → high, `0.7` → medium, `0.4` → log review). Use a valid `SLACK_WEBHOOK_URL` for paths that notify Slack.

Minimal CRITICAL bodies for each tier (add `likely_root_cause`, `recommended_actions`, `evidence`, `timeline` as in real triage):

```bash
BASE='{"severity":"CRITICAL","incident_summary":"CPU","likely_root_cause":"contention","recommended_actions":["Check CPU"],"escalate":true,"evidence":[],"timeline":[]}'

curl -s -X POST http://localhost:5678/webhook/triage-escalation -H "Content-Type: application/json" -d "$(echo $BASE | jq '. + {confidence: 0.9}')"
curl -s -X POST http://localhost:5678/webhook/triage-escalation -H "Content-Type: application/json" -d "$(echo $BASE | jq '. + {confidence: 0.7, service_name: \"payment-api\"}')"
curl -s -X POST http://localhost:5678/webhook/triage-escalation -H "Content-Type: application/json" -d "$(echo $BASE | jq '. + {confidence: 0.4}')"
```

## API routes (FastAPI)

| Method | Path | Role |
|--------|------|------|
| POST | `/n8n/mock-jira/issue` | Returns `{ key, id, self, fields }` like Jira |
| POST | `/n8n/workflow-log` | Appends one JSONL line (`N8N_WORKFLOW_LOG_DISABLE`, `N8N_WORKFLOW_LOG_JSONL`) |
| POST | `/n8n/triage-feedback` | Appends human feedback JSONL (`N8N_TRIAGE_FEEDBACK_DISABLE`, `N8N_TRIAGE_FEEDBACK_JSONL`) |

## Import / version notes

Workflows were authored for **n8n 1.73.x** (see `docker-compose.n8n.yml` image tag). If import errors appear on a newer n8n, recreate the same graph in the UI from this README or adjust node type versions in the JSON.

If **IF** conditions never match (e.g. always `not_escalated` / `no_notification`), your editor may be using old expressions: ensure **Is CRITICAL** uses `$json.body.severity` and **Should escalate** uses `$json.body.escalate` — re-import the JSON from this repo or fix the expressions in the UI.

**`triage-feedback` → `{"message":"Error in workflow"}`** — Usually the **POST triage-feedback** HTTP node failed (connection refused, or **404**). From the host, `curl -s http://127.0.0.1:8000/ | jq .n8n_triage_feedback` must show `POST /n8n/triage-feedback`; if you get **404** on that path, restart the API from this repo (`uv run serve-api`) so it loads the current `n8n_routes`. From inside Docker, the URL must be reachable (`TRIAGE_API_BASE`, default `http://host.docker.internal:8000`).

## End-to-end with real triage

```bash
# 1) API up with keys + index
uv run serve-api

# 2) n8n up, workflows imported + active

# 3) Triage then forward to ticket workflow (pipe triage JSON as-is)
curl -s -X POST http://127.0.0.1:8000/triage \
  -H "Content-Type: application/json" \
  -d @examples/sample_incident_payload.json \
| curl -s -X POST http://localhost:5678/webhook/ticket-creation \
  -H "Content-Type: application/json" -d @-
```

Adjust severity/escalate in the triage JSON to hit each branch.
