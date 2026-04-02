# Autonomous DevOps Incident Response Agent

**What this is:** an **AI-powered incident triage and diagnosis engine** — RAG over runbooks/incidents/logs, multi-source context fusion with the alert payload, heuristic guardrails plus LLM structured reasoning, and an action / escalation layer. That pattern matches **AIOps** assistants, **SRE copilots**, and internal reliability tooling at large shops.

Operational scope today: ingest alerts (JSON), retrieve knowledge, return structured triage JSON over HTTP, and drive **n8n** webhooks (Slack + mock ticketing). Later: UI, eval harness, full stack Docker, AWS deploy. For an explicit capability breakdown and the **~10% roadmap** (evidence attribution, contradiction handling, timelines), see [`docs/decisions/capabilities-and-roadmap.md`](docs/decisions/capabilities-and-roadmap.md).

**Owner:** Oluwatosin Jegede  
**Plan:** Phases **1–6** are summarized below; optional private notes in root `execution.md` (gitignored).

Secrets live in **`.env`** (copy from [`.env.example`](.env.example)). **`load_dotenv` only reads `.env`**. Never commit `.env` or real keys in `.env.example`.

---

## Build progress: Phases 1–6 (through n8n layer)

| Phase | Status | Primary artifacts |
|-------|--------|---------------------|
| **1** — Problem definition | Done | [`docs/decisions/problem-definition.md`](docs/decisions/problem-definition.md) |
| **2** — Knowledge & sample data | Done | [`data/runbooks/`](data/runbooks/), [`data/incidents/`](data/incidents/), [`data/logs/`](data/logs/), [`data/knowledge_base/`](data/knowledge_base/) |
| **3** — Local RAG | Done | [`app/rag/`](app/rag/) · FAISS index under `.rag_index/` (gitignored) |
| **4** — LangGraph triage agent | Done | [`app/agent/`](app/agent/), [`app/models/`](app/models/) |
| **5** — HTTP API | Done | [`app/api/`](app/api/) · FastAPI + JSONL audit log |
| **6** — n8n execution layer | Done | [`workflows/n8n/`](workflows/n8n/) · [`docker-compose.n8n.yml`](docker-compose.n8n.yml) · `POST /n8n/*` helpers |

### Phase 1 — Problem definition

- **Deliverable:** Product boundary and I/O semantics — who triggers the system, minimum incident payload fields, required triage outputs (summary, severity, hypothesis, actions, escalation).
- **Doc:** [`docs/decisions/problem-definition.md`](docs/decisions/problem-definition.md) (also references extended schema in code).

### Phase 2 — Knowledge & sample data

- **Deliverable:** Synthetic **operational corpus** for retrieval and demos (not production data).
- **Layout:** Runbooks under `data/runbooks/` (RAG corpus; procedures with `RB-*` IDs). Incidents under `data/incidents/` (`incident-*.md` narratives). Log bundles under `data/logs/` (`*.log` + conventions in `sample-log.md`). Supplementary ops context in `data/knowledge_base/` (escalation, ownership, first-response).
- **Reference:** [`data/README.md`](data/README.md) for globs and counts.

### Phase 3 — Local RAG

- **Deliverable:** Chunk → embed → FAISS index; top‑k retrieval with scores, `doc_type`, and `source` paths.
- **Code:** [`app/rag/`](app/rag/) (`config`, loader, chunking, embeddings, index, [`retrieve`](app/rag/retrieve.py)).
- **Corpus globs (repo root):** `data/runbooks/**/*.md`, `data/incidents/incident-*.md`, `data/logs/*.log`, `data/knowledge_base/**/*.md`, `docs/decisions/**/*.md`.
- **Commands:** `uv run rag-build` / `uv run python -m app.rag.cli build-index`; `uv run rag-query "…"` or `query` subcommand.
- **Config:** `OPENAI_API_KEY` (or OpenRouter + base URL), `EMBEDDING_MODEL`, `RAG_INDEX_DIR` (see `.env.example`).

### Phase 4 — LangGraph triage agent

- **Deliverable:** Incident JSON → normalized narrative → **same retrieval query as RAG** → LLM structured triage + guardrails.
- **Graph (nodes):** `normalize_input` → `retrieval` → `analysis` → `enrich_triage` → `decision` → `output_formatter`.
- **Models:** [`app/models/incident.py`](app/models/incident.py) (payload), [`app/models/triage.py`](app/models/triage.py) — `TriageOutput` includes `evidence[]`, `conflicting_signals_summary`, `timeline` (plus core fields).
- **Deterministic layer:** [`app/agent/signal_reasoning.py`](app/agent/signal_reasoning.py) merges **programmatic evidence** from retrieval hits, **multi-signal contradiction** heuristics on the payload, and **programmatic timeline** extraction; merged with the LLM draft in `enrich_triage`.
- **API for automation:** `run_triage(incident)` and `run_triage_with_audit(incident)` → `(result, {rag_context, retrieval_hits})` in [`app/agent/graph.py`](app/agent/graph.py).
- **CLI:** `uv run triage -f examples/sample_incident_payload.json` (needs `.env`, built index, chat-capable model).
- **Product framing:** [`docs/decisions/capabilities-and-roadmap.md`](docs/decisions/capabilities-and-roadmap.md).

### Phase 5 — HTTP API (FastAPI)

- **Deliverable:** Local backend for ingest validation and full triage over HTTP.
- **Endpoints:** `GET /` (service discovery), `GET /health`, `GET /version`, `POST /ingest-incident` (validate + normalize only), `POST /triage` (full pipeline; response body is **only** the triage JSON, same shape as CLI).
- **Run:** `uv run serve-api` or `uvicorn app.api.main:app` (optional `API_HOST`, `API_PORT`). OpenAPI: `/docs`.
- **Audit log:** Each `POST /triage` appends one line to `data/logs/triage_outputs.jsonl` (**gitignored**): `timestamp`, `input`, `output`, **`retrieved_context`**, **`top_k_sources`**. Env: `TRIAGE_AUDIT_DISABLE`, `TRIAGE_AUDIT_JSONL`, `TRIAGE_AUDIT_MAX_RAG_CHARS`. How to validate: [`docs/decisions/triage-audit-validation.md`](docs/decisions/triage-audit-validation.md).

### Phase 6 — n8n execution layer

- **Deliverable:** Run **n8n in Docker**; two **importable workflows** driven by **webhooks**; FastAPI **mock Jira** + **workflow event log** for automation glue.
- **Docker:** [`docker-compose.n8n.yml`](docker-compose.n8n.yml) — `docker compose -f docker-compose.n8n.yml up -d` → UI at **http://localhost:5678**. Uses `host.docker.internal` + `TRIAGE_API_BASE` (default `http://host.docker.internal:8000`) to reach the API from the container.
- **Workflows (import JSON in n8n, then activate):**
  - **`incident-triage-escalation`** — `POST …/webhook/triage-escalation` with **flat triage JSON**; if `severity === CRITICAL`, posts to **`SLACK_WEBHOOK_URL`** and logs via **`POST /n8n/workflow-log`**.
  - **`incident-ticket-creation`** — `POST …/webhook/ticket-creation` with flat triage JSON; if `escalate === true`, **`POST /n8n/mock-jira/issue`** and returns a mock `MOCK-*` key.
- **API helpers:** [`app/api/n8n_routes.py`](app/api/n8n_routes.py) — `POST /n8n/mock-jira/issue`, `POST /n8n/workflow-log` (append **`data/logs/n8n_workflow_events.jsonl`**, gitignored; env `N8N_WORKFLOW_LOG_DISABLE`, `N8N_WORKFLOW_LOG_JSONL`).
- **Guide:** [`workflows/n8n/README.md`](workflows/n8n/README.md) (curl examples, pipe `POST /triage` → ticket webhook).

### Tests

- **Command:** `uv run pytest` (unit + integration; integration mocks LLM where needed).
- **Layout:** `tests/unit/`, `tests/integration/`.

### Next (Phase 7+)

- **Phase 7+:** Minimal UI (e.g. Gradio), evaluation harness, full `docker-compose` stack, AWS/Terraform, CI/CD — see your local `execution.md` or future README updates.

---

## Repository layout (high level)

| Path | Purpose |
|------|---------|
| `execution.md` (local, gitignored) | Optional private build sequence and checklists |
| [`docs/decisions/`](docs/decisions/) | ADRs / product definition |
| [`docs/decisions/capabilities-and-roadmap.md`](docs/decisions/capabilities-and-roadmap.md) | Accurate product classification + elite-system roadmap |
| [`docs/decisions/triage-audit-validation.md`](docs/decisions/triage-audit-validation.md) | JSONL audit checks, leakage, eval roadmap |
| [`docs/architecture/`](docs/architecture/) | **[Architecture diagram](docs/architecture/README.md)** (`architectural-diagram.png` at repo root) |
| [`data/runbooks/`](data/runbooks/) | SRE-style procedural runbooks (`RB-*` IDs) |
| [`data/incidents/`](data/incidents/) | Synthetic postmortem-style incidents (`INC-*`) |
| [`data/logs/`](data/logs/) | Synthetic log bundles + [`sample-log.md`](data/logs/sample-log.md) |
| [`data/knowledge_base/`](data/knowledge_base/) | Escalation, ownership, tiers, first-response notes |
| [`data/README.md`](data/README.md) | Data layout and ingestion globs |
| `app/` | `app/rag/`, `app/agent/`, `app/api/` (FastAPI), `app/models/` |
| [`examples/sample_incident_payload.json`](examples/sample_incident_payload.json) | Sample JSON for `triage` CLI |
| [`workflows/n8n/`](workflows/n8n/) | n8n workflow JSON + Phase 6 runbook |
| [`docker-compose.n8n.yml`](docker-compose.n8n.yml) | Local n8n service (Phase 6) |
| `infra/terraform/` | *(Phase 10+)* |

---

## Python environment (**uv**, not manual venv + pip)

This repo uses **[uv](https://docs.astral.sh/uv/)** to create `.venv`, resolve deps from [`pyproject.toml`](pyproject.toml), and run commands with locked versions ([`uv.lock`](uv.lock)).

Install uv (pick one):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
# or: brew install uv
```

Sync and install the project (editable) + dev tools:

```bash
cd autonomous-incident-response-agent
uv sync --extra dev
```

Run RAG CLI (always via `uv run` so the right env is used):

```bash
uv run python -m app.rag.cli build-index
uv run python -m app.rag.cli query "High CPU on payment-api in production"
# or entry points:
uv run rag-build
uv run rag-query "High CPU on payment-api in production"
```

**Phase 4 — triage (needs `.env` + built RAG index + chat LLM):**

```bash
uv run python -m app.agent.cli -f examples/sample_incident_payload.json
# or: uv run triage -f examples/sample_incident_payload.json
```

**Phase 5 — HTTP API (same env as triage):**

```bash
uv run serve-api
# or: uv run uvicorn app.api.main:app --reload --host 127.0.0.1 --port 8000
```

Optional: `API_HOST`, `API_PORT` for `serve-api`.

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/version
curl -s -X POST http://127.0.0.1:8000/ingest-incident -H "Content-Type: application/json" \
  -d @examples/sample_incident_payload.json
curl -s -X POST http://127.0.0.1:8000/triage -H "Content-Type: application/json" \
  -d @examples/sample_incident_payload.json
```

OpenAPI: `http://127.0.0.1:8000/docs`

**Phase 6 — n8n (parallel terminal, API must still be running):**

```bash
docker compose -f docker-compose.n8n.yml up -d
```

Import [`workflows/n8n/incident-triage-escalation.json`](workflows/n8n/incident-triage-escalation.json) and [`workflows/n8n/incident-ticket-creation.json`](workflows/n8n/incident-ticket-creation.json) in the n8n UI, activate, then follow [`workflows/n8n/README.md`](workflows/n8n/README.md).

If `POST /triage` returns `{"detail":"Not Found"}`, something else is bound to that port or an old server is running. Check with `curl -s http://127.0.0.1:8000/` — you should see `service: autonomous-incident-response-agent` and `triage: POST /triage`. Then restart: `uv run serve-api` (or `uvicorn app.api.main:app` from the repo root).

Set `LLM_MODEL` (default `gpt-4o-mini`) in `.env` if needed. Chat uses the same `OPENAI_API_KEY` / `OPENAI_API_BASE` as embeddings unless you split providers later.

Refresh the lockfile after changing `pyproject.toml`:

```bash
uv lock
```

[`requirements.txt`](requirements.txt) is an optional mirror for non-uv workflows; **prefer `uv sync`**.

---

## Disclaimer

Runbooks, incidents, and logs are **synthetic** training/evaluation material. They are not live production data.
