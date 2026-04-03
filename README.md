# Autonomous DevOps Incident Response Agent

**What this is:** an **AI-powered incident triage and diagnosis engine** — RAG over runbooks/incidents/logs, multi-source context fusion with the alert payload, heuristic guardrails plus LLM structured reasoning, and an action / escalation layer. That pattern matches **AIOps** assistants, **SRE copilots**, and internal reliability tooling at large shops.

Operational scope today: ingest alerts (JSON), retrieve knowledge, return structured triage JSON over HTTP, optional **Gradio** at `/ui`, **Phase 12** **Next.js** triage console (local or static export to **S3** / optional **CloudFront**), **n8n** webhooks (Slack + mock ticketing), an **offline eval harness** (`triage-eval`), **Docker Compose** for local full stack, **Terraform** for **AWS** (dev/prod), and **Phase 11** — **ECR push + ECS Fargate** behind an ALB with **`.rag_index` baked** in the image and **remote state** (S3 + DynamoDB). For capability depth and the **~10% roadmap**, see [`docs/decisions/capabilities-and-roadmap.md`](docs/decisions/capabilities-and-roadmap.md).

**Owner:** Oluwatosin Jegede  
**Status:** Phases **1–13** shipped in-repo (API on ECS **dev/prod**; browser UI + **CORS**; **CloudWatch** dashboard/alarms + triage metrics). **Phase 14+**: CI/CD, TLS.

**Plan:** Detailed phase notes below; maintainer checklist in root [`execution.md`](execution.md) (tracked in git).

Secrets live in **`.env`** (copy from [`.env.example`](.env.example)). **`load_dotenv` only reads `.env`**. Never commit `.env` or real keys in `.env.example`.

### Quick start (happy path)

1. `uv sync --extra dev` (add `--extra ui` for Gradio at `/ui`).
2. `uv run rag-build` — build FAISS index under `.rag_index/` (needs `OPENAI_API_KEY` in `.env`).
3. `uv run serve-api` — API + optional `/ui` → [`/docs`](http://127.0.0.1:8000/docs).
4. **Stack in Docker:** `docker compose up -d --build` — API on host **:18080** + n8n on **:5678** ([Phase 9](#phase-9--docker-compose-full-stack)). *Or* run the API on the host and use `docker compose -f docker-compose.n8n.yml up -d` for n8n only.
5. `uv run triage-eval` — regression-style eval over [`data/eval/gold.jsonl`](data/eval/gold.jsonl) (live LLM, ~27 cases; regenerate via `python3 scripts/generate_eval_gold.py`).

| Command | Role |
|---------|------|
| `uv run rag-build` / `rag-query` | Index + ad-hoc retrieval |
| `uv run triage -f …` | One-shot triage CLI |
| `uv run serve-api` | FastAPI + OpenAPI |
| `uv run triage-eval` | Gold JSONL → Markdown report |

---

## Build progress: Phases 1–13

| Phase | Status | Primary artifacts |
|-------|--------|---------------------|
| **1** — Problem definition | Done | [`docs/decisions/problem-definition.md`](docs/decisions/problem-definition.md) |
| **2** — Knowledge & sample data | Done | [`data/runbooks/`](data/runbooks/), [`data/incidents/`](data/incidents/), [`data/logs/`](data/logs/), [`data/knowledge_base/`](data/knowledge_base/) |
| **3** — Local RAG | Done | [`app/rag/`](app/rag/) · FAISS index under `.rag_index/` (gitignored) |
| **4** — LangGraph triage agent | Done | [`app/agent/`](app/agent/), [`app/models/`](app/models/) |
| **5** — HTTP API | Done | [`app/api/`](app/api/) · FastAPI + JSONL audit log |
| **6** — n8n execution layer | Done | [`workflows/n8n/`](workflows/n8n/) · [`docker-compose.n8n.yml`](docker-compose.n8n.yml) · `POST /n8n/*` helpers |
| **7** — Minimal UI | Done | [`app/ui/`](app/ui/) · Gradio at **`/ui`** (`uv sync --extra ui`) |
| **8** — Evaluation | Done | [`app/eval/`](app/eval/) · [`data/eval/gold.jsonl`](data/eval/gold.jsonl) · `scripts/generate_eval_gold.py` · `uv run triage-eval` |
| **9** — Docker Compose | Done | [`Dockerfile`](Dockerfile) · [`docker-compose.yml`](docker-compose.yml) · n8n + API on one network |
| **10** — AWS / Terraform | Done | [`infra/terraform/`](infra/terraform/) · modules + [`envs/dev`](infra/terraform/envs/dev/) & [`envs/prod`](infra/terraform/envs/prod/) |
| **11** — Deploy to AWS | Done | [`docs/deploy/aws-ecs.md`](docs/deploy/aws-ecs.md) · [`scripts/aws/push_api_to_ecr.sh`](scripts/aws/push_api_to_ecr.sh) · **ECR digest of `:latest`** · image bakes **`.rag_index`** · SSM secret merge · [`infra/terraform/bootstrap/`](infra/terraform/bootstrap/) |
| **12** — Triage UI (Next.js) | Done | [`frontend/`](frontend/) · [`infra/terraform/modules/frontend_static_cdn/`](infra/terraform/modules/frontend_static_cdn/) · **`cors_origins`** → **`CORS_ORIGINS`** · [`scripts/aws/deploy_frontend_cdn.sh`](scripts/aws/deploy_frontend_cdn.sh) |
| **13** — Observability | Done | [`infra/terraform/modules/monitoring/`](infra/terraform/modules/monitoring/) · [`docs/deploy/observability.md`](docs/deploy/observability.md) · triage JSON + **LLM tokens** → log metrics; **p95** dashboards + **SNS-ready** alarms |

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
- **Models:** [`app/models/incident.py`](app/models/incident.py) (payload), [`app/models/triage.py`](app/models/triage.py) — `TriageOutput` includes optional `service_name`, `evidence[]`, `conflicting_signals_summary`, `timeline` (plus core fields).
- **Deterministic layer:** [`app/agent/signal_reasoning.py`](app/agent/signal_reasoning.py) merges **programmatic evidence** from retrieval hits, **multi-signal contradiction** heuristics on the payload, and **programmatic timeline** extraction; merged with the LLM draft in `enrich_triage`.
- **API for automation:** `run_triage(incident)` and `run_triage_with_audit(incident)` → `(result, {rag_context, retrieval_hits})` in [`app/agent/graph.py`](app/agent/graph.py).
- **CLI:** `uv run triage -f examples/sample_incident_payload.json` (needs `.env`, built index, chat-capable model).
- **Product framing:** [`docs/decisions/capabilities-and-roadmap.md`](docs/decisions/capabilities-and-roadmap.md).

### Phase 5 — HTTP API (FastAPI)

- **Deliverable:** Local backend for ingest validation and full triage over HTTP.
- **Endpoints:** `GET /` (service discovery), `GET /health`, `GET /version`, `POST /ingest-incident` (validate + normalize only), `POST /triage` (full pipeline; response is triage fields plus **`triage_id`** (UUID) for feedback and eval joins).
- **Run:** `uv run serve-api` or `uvicorn app.api.main:app` (optional `API_HOST`, `API_PORT`). OpenAPI: `/docs`.
- **Audit log:** Each `POST /triage` appends one line to `data/logs/triage_outputs.jsonl` (**gitignored**): **`triage_id`**, `timestamp`, `input`, `output` (includes the same **`triage_id`**), **`retrieved_context`**, **`top_k_sources`**. Env: `TRIAGE_AUDIT_DISABLE`, `TRIAGE_AUDIT_JSONL`, `TRIAGE_AUDIT_MAX_RAG_CHARS`. How to validate: [`docs/decisions/triage-audit-validation.md`](docs/decisions/triage-audit-validation.md).
- **Feedback join:** Send **`triage_id`** from the triage response on **`POST /n8n/triage-feedback`**; feedback JSONL lines include top-level **`triage_id`** for correlation with the audit file.
- **Optional hardening:** Set **`API_KEY`** in the environment to require matching header **`x-api-key`** on **`POST /ingest-incident`** and **`POST /triage`** ( **`401`** otherwise). **`GET /health`** and **`/n8n/*`** stay open for ALB checks and n8n glue. **slowapi** enforces **`10/minute`** (triage) and **`30/minute`** (ingest) per client IP, or per **`x-api-key`** when present (**`429`** on excess). Tune with **`API_RATE_LIMIT_TRIAGE`**, **`API_RATE_LIMIT_INGEST`**; **`API_RATE_LIMIT_DISABLED=1`** for tests.

### Phase 6 — n8n execution layer

- **Deliverable:** Run **n8n in Docker**; two **importable workflows** driven by **webhooks**; FastAPI **mock Jira** + **workflow event log** for automation glue.
- **Docker:** [`docker-compose.n8n.yml`](docker-compose.n8n.yml) — `docker compose -f docker-compose.n8n.yml up -d` → UI at **http://localhost:5678**. Uses `host.docker.internal` + `TRIAGE_API_BASE` (default `http://host.docker.internal:8000`) to reach the API from the container. Set **`SLACK_WEBHOOK_URL`** in repo-root **`.env`** (gitignored); Compose injects it into n8n — never commit the real URL.
- **Workflows (import JSON in n8n, then activate):**
  - **`incident-triage-escalation`** — `POST …/webhook/triage-escalation` with **flat triage JSON**; if `severity === CRITICAL`, routes by **`confidence`** (Slack + log vs Slack-only vs log-only) and sends a **rich Slack attachment** (service, root cause, actions, evidence). See [`workflows/n8n/README.md`](workflows/n8n/README.md).
  - **`incident-ticket-creation`** — `POST …/webhook/ticket-creation` with flat triage JSON; if `escalate === true`, **`POST /n8n/mock-jira/issue`** and returns a mock `MOCK-*` key.
  - **`incident-triage-feedback`** (optional) — `POST …/webhook/triage-feedback` → **`POST /n8n/triage-feedback`**; include **`triage_id`** from **`POST /triage`** plus labels (`diagnosis_correct`, `actions_useful`, etc.).
- **API helpers:** [`app/api/n8n_routes.py`](app/api/n8n_routes.py) — `POST /n8n/mock-jira/issue`, `POST /n8n/workflow-log`, `POST /n8n/triage-feedback` (append-only logs under `data/logs/`, gitignored; see env vars in [`workflows/n8n/README.md`](workflows/n8n/README.md)).
- **Guide:** [`workflows/n8n/README.md`](workflows/n8n/README.md) (curl examples, pipe `POST /triage` → ticket webhook).

### Tests

- **Command:** `uv sync --extra dev` then `uv run pytest` (unit + integration; integration mocks LLM where needed).
- **Layout:** `tests/unit/` (includes `test_eval_metrics.py` for Phase 8 metrics), `tests/integration/`.

### Phase 7 — Minimal UI (Gradio)

- **Deliverable:** Browser console on the **same process** as the API — paste incident JSON, run triage (same graph + audit as `POST /triage`), copy **`triage_id`**, submit **feedback** rows to `triage_feedback.jsonl`.
- **Install:** `uv sync --extra ui` (adds Gradio).
- **Run:** `uv run serve-api` → open **http://127.0.0.1:8000/ui/** (with default host/port). **`GET /`** includes **`gradio_ui_mounted`** — if `false`, run **`uv sync --extra ui`** or check **`ENABLE_GRADIO_UI=0`**. If **:8000** is another app (e.g. a different Docker project), use this API’s real port (Compose default **:18080** → **http://127.0.0.1:18080/ui/**). Disable the mount with **`ENABLE_GRADIO_UI=0`** (pytest sets this automatically).
- **Code:** [`app/ui/gradio_app.py`](app/ui/gradio_app.py) · display helpers [`app/ui/triage_display.py`](app/ui/triage_display.py) · shared runner [`app/api/triage_execution.py`](app/api/triage_execution.py).
- **UX:** Severity badge, color-coded confidence bar, sectioned summary / root cause / actions / timeline, evidence grouped (logs · incidents · metrics · runbooks/knowledge) in `<details>`, collapsible raw JSON, links to `/docs`, copy **`triage_id`**, Gradio toasts (`Success` / `Warning`), feedback button re-enabled on each new triage run.

### Phase 8 — Evaluation

- **Deliverable:** Gold JSONL (**~27** cases; regenerate with `python3 scripts/generate_eval_gold.py`), CLI **`uv run triage-eval`**, Markdown report (stdout or `--out`).
- **Metrics:** Severity / escalate / action-count vs gold; optional summary keywords, root-cause phrases, retrieval substring + score checks; per-case latency (mean, p95); evidence–retrieval overlap heuristic (grounding signal, not a full hallucination judge). Rows omitting those `expect` fields show `None` for the corresponding check in the report.
- **Paths:** [`data/eval/README.md`](data/eval/README.md) (format), [`data/eval/gold.jsonl`](data/eval/gold.jsonl), [`app/eval/`](app/eval/) (runner, metrics, report).
- **Run:** Same prerequisites as triage (`.env`, built index, LLM). By default **`TRIAGE_AUDIT_DISABLE`** is set for the run so eval does not flood `triage_outputs.jsonl`; use **`--keep-audit`** to append audit lines.
- **Reports:** `uv run triage-eval --out data/eval/reports/latest.md` — the **`data/eval/reports/`** contents are **gitignored** (local runs); only a **`.gitkeep`** is kept so the folder exists.

### Phase 9 — Docker Compose (full stack)

- **Deliverable:** One command brings up **FastAPI + Gradio** and **n8n** on a shared Docker network.
- **Files:** [`Dockerfile`](Dockerfile) (Python 3.12, `uv sync --frozen`, UI extra, **`curl` + explicit `HEALTHCHECK`** for ALB/ECS-style probes), [`docker-compose.yml`](docker-compose.yml), [`.dockerignore`](.dockerignore).
- **Prerequisites:** `.env` with `OPENAI_API_KEY`; on the host run **`uv run rag-build`** once so **`./.rag_index`** exists (mounted **read-only** into the API container). Optional `SLACK_WEBHOOK_URL` for n8n (same as Phase 6).
- **Persistence (not ephemeral on rebuild):** **`./data:/app/data`** (corpus paths, `data/logs` JSONL, eval outputs under `data/eval/` if written) and **`./.rag_index`** (FAISS) are bind-mounted from the host.
- **Run:**
  ```bash
  docker compose up -d --build
  ```
  - API: [http://127.0.0.1:18080/docs](http://127.0.0.1:18080/docs), UI: [http://127.0.0.1:18080/ui](http://127.0.0.1:18080/ui) — **default host port `18080`** avoids clashes with local **`serve-api`** on **:8000**.
  - To publish the API on host **:8000** instead: `COMPOSE_API_PORT=8000 docker compose up -d --build`.
  - n8n: [http://localhost:5678](http://localhost:5678) — import and activate workflows from [`workflows/n8n/`](workflows/n8n/). **`TRIAGE_API_BASE`** is set to **`http://api:8000`** inside Compose (do not override to `host.docker.internal` for this stack).
- **End-to-end check (definition of done before Phase 10):** With Compose up and **n8n workflow `incident-ticket-creation` imported + active**, run from repo root:
  ```bash
  ./scripts/e2e_stack_check.sh
  ```
  Default `API_BASE` is **http://127.0.0.1:18080** (Compose default). For a host-only API on **:8000**, run `API_BASE=http://127.0.0.1:8000 ./scripts/e2e_stack_check.sh`. The script: **`GET /health`** → **`POST /triage`** (validates `triage_id`, severity, actions, non-empty **evidence**; optional **`STRICT_RAG_EVIDENCE=1`** requires a `data/` source in evidence) → **`POST …/webhook/ticket-creation`** (mock Jira path). **`SKIP_TRIAGE=1`** or **`SKIP_N8N=1`** to isolate steps.
- **n8n-only** (API on host): keep using [`docker-compose.n8n.yml`](docker-compose.n8n.yml) and `TRIAGE_API_BASE=http://host.docker.internal:8000`.

### Pre-cloud manual validation

Before AWS, run through **[`docs/validation/pre-cloud-validation.md`](docs/validation/pre-cloud-validation.md)** (triage quality, n8n, failure modes, latency). Use **`scripts/benchmark_triage_latency.sh`** to compare host vs Docker wall time for `/triage`.

### Phase 10 — AWS with Terraform

- **Deliverable:** `terraform init` / `plan` / `apply` per environment; VPC, subnets, security groups, ECR, ALB, ECS on **Fargate**, IAM, CloudWatch logs, optional **SSM** for `OPENAI_API_KEY`.
- **Guide:** [`infra/terraform/README.md`](infra/terraform/README.md).
- **Layouts:** [`infra/terraform/modules/`](infra/terraform/modules/) · [`infra/terraform/envs/dev/`](infra/terraform/envs/dev/) · [`infra/terraform/envs/prod/`](infra/terraform/envs/prod/). Copy `terraform.tfvars.example` → `terraform.tfvars` (gitignored).

### Phase 11 — Deploy API to AWS (ECR + ECS)

- **Deliverable:** Push API image to **ECR**, ECS **Fargate** service behind **ALB**, **`GET /health`** via Terraform **`alb_url`** (separate **dev** / **prod** stacks).
- **Runbook:** [`docs/deploy/aws-ecs.md`](docs/deploy/aws-ecs.md) — SSM for secrets (`openai_api_key_ssm_parameter` / `ssm_secrets`), **`uv run rag-build`**, then **`./scripts/aws/push_api_to_ecr.sh dev`** or **`prod`** (immutable tag + **`:latest`**, **`terraform apply`** pins digest; **`linux/amd64`** for Fargate).
- **RAG on Fargate:** the **Docker image bakes `.rag_index/`**; Compose still **bind-mounts** a host-built index for local dev.

### Phase 12 — Triage console (Next.js)

- **Deliverable:** Portfolio-style **incident triage UI** — Monaco JSON editor, `POST /triage`, evidence and feedback panels; **`output: 'export'`** for static hosting.
- **Local:** [`frontend/README.md`](frontend/README.md) — `npm run dev` with repo-root API (`CORS_ORIGINS` / defaults for `localhost:3000`).
- **AWS:** Terraform creates S3 (and optional CloudFront); **`./scripts/aws/deploy_frontend_cdn.sh dev|prod`** builds with **`NEXT_PUBLIC_API_BASE_URL`** from **`alb_url`**. Add **`triage_ui_url`** to **`cors_origins`**, **`terraform apply`**, then **push API image** so ECS sees **`CORS_ORIGINS`**.

### Phase 13 — Observability (CloudWatch)

- **Deliverable:** Dashboard (ALB **rpm**, latency **avg+p95**, **4xx/5xx** split, ECS, triage outcomes + **tokens**, triage duration **avg+p95**), **alarms** (5xx, unhealthy, **p95 latency**, **ECS CPU**, **triage max duration**). Runbook: [`docs/deploy/observability.md`](docs/deploy/observability.md).
- **App:** Each triage emits one JSON line to stdout and **`aira.triage`** (`triage_id`, `outcome`, `duration_ms`, `severity`, **LLM token counts**). Disable with **`TRIAGE_METRICS_LOG_DISABLE=1`**.

### Next (Phase 14+)

- **CI/CD**, **TLS** in front of ALB.

---

## Repository layout (high level)

| Path | Purpose |
|------|---------|
| [`execution.md`](execution.md) | Build order, phases, milestones |
| [`docs/decisions/`](docs/decisions/) | ADRs / product definition |
| [`docs/validation/pre-cloud-validation.md`](docs/validation/pre-cloud-validation.md) | Manual checks before cloud (triage, n8n, resilience, latency) |
| [`docs/decisions/capabilities-and-roadmap.md`](docs/decisions/capabilities-and-roadmap.md) | Accurate product classification + elite-system roadmap |
| [`docs/decisions/triage-audit-validation.md`](docs/decisions/triage-audit-validation.md) | JSONL audit checks, leakage, eval roadmap |
| [`docs/architecture/`](docs/architecture/) | **[Architecture diagram](docs/architecture/README.md)** (`architectural-diagram.png` at repo root) |
| [`data/runbooks/`](data/runbooks/) | SRE-style procedural runbooks (`RB-*` IDs) |
| [`data/incidents/`](data/incidents/) | Synthetic postmortem-style incidents (`INC-*`) |
| [`data/logs/`](data/logs/) | Synthetic log bundles + [`sample-log.md`](data/logs/sample-log.md) |
| [`data/knowledge_base/`](data/knowledge_base/) | Escalation, ownership, tiers, first-response notes |
| [`data/README.md`](data/README.md) | Data layout and ingestion globs |
| `app/` | `app/rag/`, `app/agent/`, `app/api/` (FastAPI), `app/models/`, `app/ui/` (Gradio), `app/eval/` (Phase 8) |
| [`data/eval/`](data/eval/) | Gold JSONL + eval README |
| [`examples/sample_incident_payload.json`](examples/sample_incident_payload.json) | Sample JSON for `triage` CLI |
| [`scripts/e2e_stack_check.sh`](scripts/e2e_stack_check.sh) | Health + `/triage` + n8n webhook smoke test |
| [`scripts/benchmark_triage_latency.sh`](scripts/benchmark_triage_latency.sh) | Repeated `POST /triage` timings (mean / p95) |
| [`workflows/n8n/`](workflows/n8n/) | n8n workflow JSON + Phase 6 runbook |
| [`docker-compose.yml`](docker-compose.yml) | Phase 9 — API + n8n |
| [`docker-compose.n8n.yml`](docker-compose.n8n.yml) | Phase 6 — n8n only |
| [`Dockerfile`](Dockerfile) | Phase 9 — API image |
| [`infra/terraform/`](infra/terraform/) | Phase 10–12 — modular Terraform, remote state bootstrap, `envs/dev` & `envs/prod`, static UI bucket |
| [`frontend/`](frontend/) | Phase 12 — Next.js triage console (static export → S3) |
| [`docs/deploy/aws-ecs.md`](docs/deploy/aws-ecs.md) | Phase 11–12 — ECR push, ECS rollout, SSM, hosted UI + CORS |
| [`docs/deploy/observability.md`](docs/deploy/observability.md) | Phase 13 — CloudWatch dashboard, alarms, triage log metrics |
| [`scripts/aws/push_api_to_ecr.sh`](scripts/aws/push_api_to_ecr.sh) | Phase 11 — build/push + **`terraform apply`** (ECS pins **`:latest`** digest) |
| [`scripts/aws/deploy_frontend_cdn.sh`](scripts/aws/deploy_frontend_cdn.sh) | Phase 12 — static build + **`aws s3 sync`** |
| [`scripts/aws/verify_triage_cors_preflight.sh`](scripts/aws/verify_triage_cors_preflight.sh) | Phase 12 — **`OPTIONS /triage`** CORS smoke test |

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

**Phase 8 — evaluation (same env; calls live LLM per gold row):**

```bash
uv run triage-eval
# Markdown report to file:
uv run triage-eval --out data/eval/reports/latest.md
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
# When API_KEY is set on the server, add: -H "x-api-key: <same value>"
```

OpenAPI: `http://127.0.0.1:8000/docs`

**Phase 7 — Gradio UI (optional extra, same server as Phase 5):**

```bash
uv sync --extra ui
uv run serve-api
# Browser: http://127.0.0.1:8000/ui
```

**Phase 9 — full stack (API + n8n in Docker):**

```bash
# After: uv run rag-build  and  .env with OPENAI_API_KEY
docker compose up -d --build
# API: http://127.0.0.1:18080/docs  (override with COMPOSE_API_PORT=8000 if you want :8000)
```

**Phase 6 — n8n only (API on host in another terminal):**

```bash
docker compose -f docker-compose.n8n.yml up -d
```

Import and activate in n8n: [`incident-triage-escalation.json`](workflows/n8n/incident-triage-escalation.json), [`incident-ticket-creation.json`](workflows/n8n/incident-ticket-creation.json), and optionally [`incident-triage-feedback.json`](workflows/n8n/incident-triage-feedback.json) — then follow [`workflows/n8n/README.md`](workflows/n8n/README.md).

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
