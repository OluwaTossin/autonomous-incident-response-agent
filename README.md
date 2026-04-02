# Autonomous DevOps Incident Response Agent

AI-assisted incident triage: ingest alerts, retrieve runbooks and historical context, reason over logs, classify severity, suggest remediation, and (later) trigger workflows via n8n and deploy on AWS.

**Owner:** Oluwatosin Jegede  
**Plan:** See [`execution.md`](execution.md) for phases, milestones, and deliverables.

---

## Current status

| Phase | Status | Notes |
|-------|--------|--------|
| **1** — Problem definition | Done | [`docs/decisions/problem-definition.md`](docs/decisions/problem-definition.md) |
| **2** — Knowledge & sample data | **Done** | Runbooks, incidents, logs, and `data/knowledge_base/` meet plan thresholds (see `execution.md`) |
| **3** — Local RAG | Next | `app/rag/` loader → chunk → embed → retrieve |

Secrets: copy [`.env.example`](.env.example) to `.env` (never commit `.env`). This project assumes **OpenAI** and/or **OpenRouter** keys for LLM phases.

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
| `app/` | *(Phase 3+)* API, agent, RAG |
| `workflows/n8n/` | *(Phase 6+)* |
| `infra/terraform/` | *(Phase 10+)* |

---

## Phase 3 quick prep

1. Python 3.11+ virtualenv; install deps when `pyproject.toml` / `requirements.txt` exist.  
2. Point the RAG document loader at:
   - `docs/runbooks/**/*.md`
   - `data/incidents/incident-*.md`
   - `data/logs/*.log`
   - `data/knowledge_base/**/*.md`  
3. Use `OPENAI_API_KEY` or `OPENROUTER_API_KEY` per `.env.example`.

---

## Disclaimer

Runbooks, incidents, and logs are **synthetic** training/evaluation material. They are not live production data.
