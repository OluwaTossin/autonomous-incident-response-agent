# Autonomous DevOps Incident Response Agent

**What this is:** an **AI-powered incident triage and diagnosis engine** — RAG over runbooks/incidents/logs, multi-source context fusion with the alert payload, heuristic guardrails plus LLM structured reasoning, and an action / escalation layer. That pattern matches **AIOps** assistants, **SRE copilots**, and internal reliability tooling at large shops.

Operational scope today: ingest alerts (JSON), retrieve knowledge, return structured triage JSON. Later: workflows (n8n) and AWS deploy. For an explicit capability breakdown and the **~10% roadmap** (evidence attribution, contradiction handling, timelines), see [`docs/decisions/capabilities-and-roadmap.md`](docs/decisions/capabilities-and-roadmap.md).

**Owner:** Oluwatosin Jegede  
**Plan:** Phases and deliverables are tracked in this README; keep a private `execution.md` in the repo root if you want a longer checklist (file is gitignored).

---

## Current status

| Phase | Status | Notes |
|-------|--------|--------|
| **1** — Problem definition | Done | [`docs/decisions/problem-definition.md`](docs/decisions/problem-definition.md) |
| **2** — Knowledge & sample data | **Done** | Runbooks, incidents, logs, `data/knowledge_base/` |
| **3** — Local RAG | **Done** | `app/rag/` + FAISS; `uv run python -m app.rag.cli build-index` / `query "…"` |
| **4** — LangGraph agent | **Done** | `app/agent/` + `uv run triage -f examples/sample_incident_payload.json` |

Secrets live in **`.env`** at the repo root (copy from [`.env.example`](.env.example)). **`load_dotenv` only reads `.env`** — not `.env.example`. Never commit `.env` or put real keys in `.env.example`.

---

## Repository layout (high level)

| Path | Purpose |
|------|---------|
| `execution.md` (local, gitignored) | Optional private build sequence and checklists |
| [`docs/decisions/`](docs/decisions/) | ADRs / product definition |
| [`docs/decisions/capabilities-and-roadmap.md`](docs/decisions/capabilities-and-roadmap.md) | Accurate product classification + elite-system roadmap |
| [`docs/architecture/`](docs/architecture/) | **[Architecture diagram](docs/architecture/README.md)** (`architectural-diagram.png` at repo root) |
| [`data/runbooks/`](data/runbooks/) | SRE-style procedural runbooks (`RB-*` IDs) |
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

- `data/runbooks/**/*.md`
- `data/incidents/incident-*.md`, `sample-incident.md`
- `data/logs/*.log`
- `data/knowledge_base/**/*.md`
- `docs/decisions/**/*.md`

Set `OPENAI_API_KEY` (or `OPENROUTER_API_KEY` + `OPENAI_API_BASE` if your provider is OpenAI-compatible). See [`.env.example`](.env.example).

---

## Disclaimer

Runbooks, incidents, and logs are **synthetic** training/evaluation material. They are not live production data.
