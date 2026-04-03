# Autonomous DevOps Incident Response Agent

[![CI](https://github.com/OluwaTossin/autonomous-incident-response-agent/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/OluwaTossin/autonomous-incident-response-agent/actions/workflows/ci.yml)

AI-assisted **incident triage**: RAG over runbooks, incidents, and logs; LangGraph agent with guardrails; structured JSON over HTTP; optional UIs and n8n automation. Aligned with **AIOps** / **SRE copilot** patterns.

**Maintainer:** Oluwatosin Jegede

---

## Table of contents

- [Overview](#overview)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [Documentation](#documentation)
- [Project status & branches](#project-status--branches)
- [Build phases (summary)](#build-phases-summary)
- [Repository layout](#repository-layout)
- [Development](#development)
- [Testing](#testing)
- [Docker Compose & n8n](#docker-compose--n8n)
- [Contributing](#contributing)
- [Disclaimer](#disclaimer)

---

## Overview

The service ingests **alert-style JSON**, retrieves relevant operational context, and returns **structured triage** (summary, severity, hypothesis, actions, escalation). Sample data and runbooks are **synthetic** (see [Disclaimer](#disclaimer)).

**Current closure:** Phases **1–14** are implemented (local dev through **AWS ECS**, **CloudWatch**, **GitHub Actions**). Optional extensions (e.g. TLS, Phase 15 backlog) are **out of scope for this closure** — see [`execution.md`](execution.md).

Deeper product framing: [`docs/decisions/capabilities-and-roadmap.md`](docs/decisions/capabilities-and-roadmap.md).

---

## Features

- **RAG** — FAISS index over runbooks, incidents, logs, knowledge base (`uv run rag-build`)
- **Agent** — LangGraph pipeline: normalize → retrieve → analyze → enrich → decide → format
- **API** — FastAPI: `POST /triage`, `POST /ingest-incident`, OpenAPI at `/docs`, optional `API_KEY` + rate limits
- **Audit & feedback** — JSONL audit; `triage_id` for joins; n8n + Gradio feedback paths
- **UIs** — Gradio at `/ui`; Next.js triage console in [`frontend/`](frontend/) (static export → S3)
- **Automation** — n8n workflows (Slack, mock Jira) — [`workflows/n8n/`](workflows/n8n/)
- **Eval** — Gold set + `uv run triage-eval` — [`data/eval/`](data/eval/)
- **AWS** — Terraform **dev/prod**, ECS Fargate, ALB, ECR, SSM secrets, optional static UI CDN
- **Observability** — CloudWatch dashboard, triage log metrics, alarms — [`docs/deploy/observability.md`](docs/deploy/observability.md)
- **CI/CD** — GitHub Actions (lint, tests, Terraform validate, frontend + Docker builds) — [`docs/deploy/ci.md`](docs/deploy/ci.md)

---

## Prerequisites

| Requirement | Notes |
|-------------|--------|
| **Python** | 3.11+ (see [`pyproject.toml`](pyproject.toml)) |
| **uv** | [Install uv](https://docs.astral.sh/uv/) — package manager and virtualenv |
| **OpenAI (or compatible)** | `OPENAI_API_KEY` in `.env` for embeddings + chat |
| **Docker** | Optional; for Compose (API + n8n) and local n8n |
| **AWS CLI / Terraform** | For deploy paths — see deploy docs |

Copy [`.env.example`](.env.example) → **`.env`**. Only **`.env`** is loaded by the app (never commit secrets).

---

## Quick start

```bash
uv sync --extra dev          # add --extra ui for Gradio at /ui
cp .env.example .env         # set OPENAI_API_KEY
uv run rag-build             # builds .rag_index/ (gitignored)
uv run serve-api             # http://127.0.0.1:8000/docs
```

| Command | Purpose |
|---------|---------|
| `uv run rag-build` / `rag-query` | Index + ad-hoc retrieval |
| `uv run triage -f …` | One-shot triage CLI |
| `uv run serve-api` | FastAPI + OpenAPI |
| `uv run triage-eval` | Gold JSONL → report (~27 cases; live LLM) |

**Full stack (API + n8n):** after `rag-build`, `docker compose up -d --build` — API **:18080**, n8n **:5678**. See [Docker Compose & n8n](#docker-compose--n8n).

---

## Documentation

| Topic | Link |
|-------|------|
| Phased build log, milestones, closure | [`execution.md`](execution.md) |
| Branches (`dev` / `main`), GitHub secrets | [`docs/contributing.md`](docs/contributing.md) |
| Deploy API to ECS / ECR / SSM | [`docs/deploy/aws-ecs.md`](docs/deploy/aws-ecs.md) |
| CloudWatch dashboard & triage metrics | [`docs/deploy/observability.md`](docs/deploy/observability.md) |
| GitHub Actions CI & optional deploy | [`docs/deploy/ci.md`](docs/deploy/ci.md) |
| Terraform layout & remote state | [`infra/terraform/README.md`](infra/terraform/README.md) |
| n8n workflows & webhooks | [`workflows/n8n/README.md`](workflows/n8n/README.md) |
| Next.js triage UI | [`frontend/README.md`](frontend/README.md) |
| Pre-cloud validation | [`docs/validation/pre-cloud-validation.md`](docs/validation/pre-cloud-validation.md) |
| Problem definition / ADRs | [`docs/decisions/`](docs/decisions/) |
| Data corpus layout | [`data/README.md`](data/README.md) |

---

## Project status & branches

- **Shipped:** Phases **1–14** (see [Build phases (summary)](#build-phases-summary)).
- **Workflow:** develop on **`dev`**, promote via **PR → `main`** — [`docs/contributing.md`](docs/contributing.md).
- **Future:** TLS, Phase 15 ideas, deeper n8n metrics — tracked in [`execution.md`](execution.md), not part of the current closure.

---

## Build phases (summary)

| Phase | Status | Primary artifacts |
|-------|--------|-------------------|
| **1** — Problem definition | Done | [`docs/decisions/problem-definition.md`](docs/decisions/problem-definition.md) |
| **2** — Knowledge & sample data | Done | [`data/runbooks/`](data/runbooks/), [`data/incidents/`](data/incidents/), [`data/logs/`](data/logs/), [`data/knowledge_base/`](data/knowledge_base/) |
| **3** — Local RAG | Done | [`app/rag/`](app/rag/) · `.rag_index/` (gitignored) |
| **4** — LangGraph agent | Done | [`app/agent/`](app/agent/), [`app/models/`](app/models/) |
| **5** — HTTP API | Done | [`app/api/`](app/api/) |
| **6** — n8n | Done | [`workflows/n8n/`](workflows/n8n/), [`docker-compose.n8n.yml`](docker-compose.n8n.yml) |
| **7** — Gradio UI | Done | [`app/ui/`](app/ui/) · `/ui` |
| **8** — Evaluation | Done | [`app/eval/`](app/eval/), [`data/eval/gold.jsonl`](data/eval/gold.jsonl) |
| **9** — Docker Compose | Done | [`Dockerfile`](Dockerfile), [`docker-compose.yml`](docker-compose.yml) |
| **10** — Terraform | Done | [`infra/terraform/`](infra/terraform/) |
| **11** — ECS / ECR | Done | [`docs/deploy/aws-ecs.md`](docs/deploy/aws-ecs.md), [`scripts/aws/push_api_to_ecr.sh`](scripts/aws/push_api_to_ecr.sh) |
| **12** — Next.js UI | Done | [`frontend/`](frontend/), [`scripts/aws/deploy_frontend_cdn.sh`](scripts/aws/deploy_frontend_cdn.sh) |
| **13** — Observability | Done | [`docs/deploy/observability.md`](docs/deploy/observability.md), [`infra/terraform/modules/monitoring/`](infra/terraform/modules/monitoring/) |
| **14** — CI/CD | Done | [`.github/workflows/ci.yml`](.github/workflows/ci.yml), [`docs/deploy/ci.md`](docs/deploy/ci.md) |

**Per-phase narrative** (endpoints, env vars, n8n behaviour, AWS steps): see **[`execution.md`](execution.md)** — kept there to avoid duplicating a long spec in this file.

---

## Repository layout

| Path | Purpose |
|------|---------|
| [`execution.md`](execution.md) | Build order, detailed phases, milestones |
| [`docs/contributing.md`](docs/contributing.md) | Branching & GitHub Actions secrets |
| [`docs/decisions/`](docs/decisions/) | ADRs, problem definition, roadmap |
| [`docs/architecture/`](docs/architecture/) | Architecture diagram |
| [`app/`](app/) | `rag`, `agent`, `api`, `models`, `ui`, `eval` |
| [`data/`](data/) | Runbooks, incidents, logs, eval gold set |
| [`frontend/`](frontend/) | Next.js triage console |
| [`workflows/n8n/`](workflows/n8n/) | Importable n8n JSON + README |
| [`infra/terraform/`](infra/terraform/) | Modules, `envs/dev`, `envs/prod`, bootstrap |
| [`scripts/`](scripts/) | E2E check, benchmarks, AWS helper scripts |
| [`examples/sample_incident_payload.json`](examples/sample_incident_payload.json) | Sample payload for CLI / API |

---

## Development

Uses **[uv](https://docs.astral.sh/uv/)** with [`pyproject.toml`](pyproject.toml) and [`uv.lock`](uv.lock).

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # or: brew install uv
cd autonomous-incident-response-agent
uv sync --extra dev
```

**Triage CLI** (needs `.env`, index, chat model):

```bash
uv run triage -f examples/sample_incident_payload.json
```

**API** (same environment):

```bash
uv run serve-api
curl -s http://127.0.0.1:8000/health
curl -s -X POST http://127.0.0.1:8000/triage -H "Content-Type: application/json" \
  -d @examples/sample_incident_payload.json
```

With **`API_KEY`** set on the server, add header `x-api-key: <value>`. OpenAPI: `/docs`.

**Gradio:** `uv sync --extra ui` then `uv run serve-api` → `http://127.0.0.1:8000/ui` (Compose default API port is **18080**).

**Eval:** `uv run triage-eval` — optional `--limit N`, `--out path/to/report.md`.

**Lockfile:** after editing dependencies, `uv lock`. [`requirements.txt`](requirements.txt) is optional; prefer **`uv sync`**.

If `POST /triage` returns 404, confirm nothing else is bound to the port: `curl -s http://127.0.0.1:8000/` should show this service’s discovery JSON.

---

## Testing

```bash
uv sync --extra dev
uv run pytest
```

Layout: `tests/unit/`, `tests/integration/` (integration mocks the LLM where appropriate).

---

## Docker Compose & n8n

```bash
uv run rag-build
docker compose up -d --build
```

- API: `http://127.0.0.1:18080/docs` · UI: `http://127.0.0.1:18080/ui` · n8n: `http://localhost:5678`
- Host port: override with `COMPOSE_API_PORT=8000` if needed.
- E2E smoke: [`scripts/e2e_stack_check.sh`](scripts/e2e_stack_check.sh) (see script for `API_BASE`).

**n8n only** (API on host): `docker compose -f docker-compose.n8n.yml up -d` — full guide: [`workflows/n8n/README.md`](workflows/n8n/README.md).

**AWS image:** `.rag_index` is baked in the Dockerfile; run `rag-build` before `docker build`. Rollout: [`scripts/aws/push_api_to_ecr.sh`](scripts/aws/push_api_to_ecr.sh) and [`docs/deploy/aws-ecs.md`](docs/deploy/aws-ecs.md).

---

## Contributing

Branch **`dev`**, open PRs to **`main`**. CI expectations and optional secrets: [`docs/contributing.md`](docs/contributing.md).

---

## Disclaimer

Runbooks, incidents, and logs in this repository are **synthetic** training and evaluation material. They are not live production data.
