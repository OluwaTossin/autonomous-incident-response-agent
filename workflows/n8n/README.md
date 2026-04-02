# Phase 6 — n8n execution layer

Local **[n8n](https://n8n.io/)** workflows that react to **triage-shaped JSON** (same structure as `POST /triage` responses). They call your FastAPI app for a **mock Jira** create and an optional **workflow event log**.

## Prerequisites

1. **FastAPI** running on the host (default `http://127.0.0.1:8000`): `uv run serve-api`
2. **Docker** (for n8n)
3. Optional: **Slack Incoming Webhook** URL in `.env` as `SLACK_WEBHOOK_URL` (needed for the CRITICAL branch in `incident-triage-escalation`)

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

**Activate** each workflow (toggle in n8n UI) so webhooks listen.

### Docker → host API

Compose sets `TRIAGE_API_BASE` default to `http://host.docker.internal:8000` and `extra_hosts: host.docker.internal:host-gateway` (Linux-friendly). If the API is elsewhere, export before `up`:

```bash
export TRIAGE_API_BASE=http://host.docker.internal:8000
docker compose -f docker-compose.n8n.yml up -d
```

## Workflow behaviour

### `incident-triage-escalation`

1. **Webhook** accepts a **flat triage JSON** object (same fields as `POST /triage` returns).
2. If **`severity === "CRITICAL"`**:
   - **Notify Slack** — `POST` to `$env.SLACK_WEBHOOK_URL` with the triage JSON in the message text.
   - **Workflow log** — `POST` to `{TRIAGE_API_BASE}/n8n/workflow-log` with the triage body (append-only JSONL on the API host: `data/logs/n8n_workflow_events.jsonl`, gitignored).
3. **Respond to Webhook** — JSON status (`slack_and_log` vs `no_notification`).

If `SLACK_WEBHOOK_URL` is empty, the CRITICAL branch fails at the HTTP node — set a real webhook or temporarily change the workflow in the UI.

### `incident-ticket-creation`

1. **Webhook** accepts a **flat triage JSON** object.
2. If **`escalate === true`** (boolean):
   - **Mock Jira create** — `POST {TRIAGE_API_BASE}/n8n/mock-jira/issue` with summary + description derived from triage.
3. **Respond** — includes mock `ticket` key or `not_escalated`.

## Test with curl

POST the **triage JSON** directly (no wrapper):

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

To test **CRITICAL** + Slack, set `"severity":"CRITICAL"` and a valid `SLACK_WEBHOOK_URL` in the environment passed to the n8n container.

## API routes (FastAPI)

| Method | Path | Role |
|--------|------|------|
| POST | `/n8n/mock-jira/issue` | Returns `{ key, id, self, fields }` like Jira |
| POST | `/n8n/workflow-log` | Appends one JSONL line (`N8N_WORKFLOW_LOG_DISABLE`, `N8N_WORKFLOW_LOG_JSONL`) |

## Import / version notes

Workflows were authored for **n8n 1.73.x** (see `docker-compose.n8n.yml` image tag). If import errors appear on a newer n8n, recreate the same graph in the UI from this README or adjust node type versions in the JSON.

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
