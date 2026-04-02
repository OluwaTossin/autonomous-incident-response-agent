# Autonomous DevOps Incident Response Agent

AI-assisted incident triage: ingest alerts, retrieve runbooks and historical context, reason over logs, classify severity, suggest remediation, and (later) trigger workflows via n8n and deploy on AWS.

**Owner:** Oluwatosin Jegede  
**Plan:** See [`execution.md`](execution.md) for phases, milestones, and deliverables.

---

## Current status

| Phase | Status | Notes |
|-------|--------|--------|
| **1** — Problem definition | Done | [`docs/decisions/problem-definition.md`](docs/decisions/problem-definition.md) |
| **2** — Knowledge & sample data | **Done** | Runbooks, incidents, logs, `data/knowledge_base/` (see `execution.md`) |
| **3** — Local RAG | **Done** | `app/rag/` + FAISS; `uv run python -m app.rag.cli build-index` / `query "…"` |
| **4** — LangGraph agent | **Done** | `app/agent/` + `uv run triage -f examples/sample_incident_payload.json` |

Secrets live in **`.env`** at the repo root (copy from [`.env.example`](.env.example)). **`load_dotenv` only reads `.env`** — not `.env.example`. Never commit `.env` or put real keys in `.env.example`.

---

## Repository layout (high level)

| Path | Purpose |
|------|---------|
| [`execution.md`](execution.md) | Build sequence and checklists |
| [`docs/decisions/`](docs/decisions/) | ADRs / product definition |
| [`docs/architecture/`](docs/architecture/) | **[Architecture diagram](docs/architecture/README.md)** (`architectural-diagram.png` at repo root) |
| [`docs/runbooks/`](docs/runbooks/) | SRE-style procedural runbooks (`RB-*` IDs) |
| [`data/incidents/`](data/incidents/) | Synthetic postmortem-style incidents (`INC-*`) |
| [`data/logs/`](data/logs/) | Synthetic log bundles + [`sample-log.md`](data/logs/sample-log.md) |
| [`data/knowledge_base/`](data/knowledge_base/) | Escalation, ownership, tiers, first-response notes |
| [`data/README.md`](data/README.md) | Data layout and ingestion globs |
| `app/` | `app/rag/` (FAISS), `app/agent/` (LangGraph triage), `app/models/` |
| [`examples/sample_incident_payload.json`](examples/sample_incident_payload.json) | Sample JSON for `triage` CLI |
| `workflows/n8n/` | *(Phase 6+)* |
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

Set `LLM_MODEL` (default `gpt-4o-mini`) in `.env` if needed. Chat uses the same `OPENAI_API_KEY` / `OPENAI_API_BASE` as embeddings unless you split providers later.

Refresh the lockfile after changing `pyproject.toml`:

```bash
uv lock
```

[`requirements.txt`](requirements.txt) is an optional mirror for non-uv workflows; **prefer `uv sync`**.

---

## Phase 3 — RAG corpus (already wired in code)

The loader indexes (from repo root):

- `docs/runbooks/**/*.md`
- `data/incidents/incident-*.md`, `sample-incident.md`
- `data/logs/*.log`
- `data/knowledge_base/**/*.md`
- `docs/decisions/**/*.md`

Set `OPENAI_API_KEY` (or `OPENROUTER_API_KEY` + `OPENAI_API_BASE` if your provider is OpenAI-compatible). See [`.env.example`](.env.example).

---

## Disclaimer

Runbooks, incidents, and logs are **synthetic** training/evaluation material. They are not live production data.
