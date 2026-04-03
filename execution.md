# Execution Plan

**Project:** Autonomous DevOps Incident Response Agent

This document is the single source of truth for build order, scope, and milestones. Prefer shipping local value before cloud complexity.

### Phase completion (rolling)

| Phase | Status | Evidence |
|-------|--------|----------|
| **1** | Done | `docs/decisions/problem-definition.md` |
| **2** | **Done** | `data/incidents/`, `data/logs/`, `data/knowledge_base/`, `data/runbooks/` — see Phase 2 inventory |
| **3** | **Done** | `app/rag/` + FAISS; `uv run python -m app.rag.cli build-index` then `query "…"` returns runbook/log/incident hits |
| **4** | **Done** | `app/agent/` LangGraph: normalize → RAG → LLM structured triage → decision rules → JSON; `uv run triage -f examples/sample_incident_payload.json` |
| **5** | **Done** | `app/api/` FastAPI — `POST /triage`, `GET /health`, etc.; `uv run serve-api` |
| **6** | **Done** | `docker-compose.n8n.yml`, `workflows/n8n/` — escalation + ticket workflows |
| **7** | **Done** | `app/ui/` Gradio at `/ui` |
| **8** | **Done** | `app/eval/`, `data/eval/gold.jsonl`, `uv run triage-eval` |
| **9** | **Done** | `Dockerfile`, `docker-compose.yml` — API + n8n full stack locally |
| **10** | **Done** | `infra/terraform/modules/*`, `infra/terraform/envs/dev`, `envs/prod` — VPC, ECR, ALB, ECS Fargate, IAM, logs, SSM-ready |
| **11** | **Done** | `docs/deploy/aws-ecs.md`, `scripts/aws/push_api_to_ecr.sh`, `infra/terraform/bootstrap/` — ECR digest pinning, merged SSM secrets, Dockerfile bakes `.rag_index`, remote state S3+DynamoDB |
| **12** | **Done** | `frontend/` (Next.js static export), `infra/terraform/modules/frontend_static_cdn/`, `cors_origins` → `CORS_ORIGINS` on ECS, FastAPI `CORSMiddleware`, `scripts/aws/deploy_frontend_cdn.sh`, `verify_triage_cors_preflight.sh` |

---

## 1. Project goal

Build an AI-powered incident response system that can:

- Receive operational alerts
- Retrieve relevant runbook knowledge
- Reason over logs and context
- Classify severity
- Suggest remediation
- Trigger deterministic workflows for escalation or response

**Business value:** Reduces triage time, improves consistency of first response, and turns fragmented operational knowledge into an executable support layer.

---

## 2. What you are building (five parts)

**Visual:** [`docs/architecture/README.md`](docs/architecture/README.md) (diagram: `architectural-diagram.png`).

| Layer | Role |
|--------|------|
| **Ingress** | Receives incident events (UI, webhook, monitoring). |
| **Reasoning** | LLM-driven agent interprets the issue and decides what to do. |
| **Retrieval** | Pulls runbooks, past incidents, notes, and remediation guidance. |
| **Workflow** | n8n executes deterministic actions (Slack, tickets, logging, webhooks). Webhook nodes can act as API triggers and return output. |
| **Deployment & operations** | Containers; later AWS. **AWS Fargate** fits this phase: run containers without managing EC2. |

---

## 3. Prerequisites (before Phase 1)

### 3.1 Accounts and access

- [ ] GitHub account
- [ ] AWS account (not required until later phases)
- [ ] LLM access: **OpenAI** and/or **OpenRouter** (this project assumes these; other providers optional later)
- [ ] (Optional) Slack workspace for alerts
- [ ] (Optional) Hosted vector DB (e.g. Pinecone, Weaviate Cloud)

### 3.2 Local tools

Install and verify:

- [ ] Git
- [ ] Python 3.11+
- [ ] **[uv](https://docs.astral.sh/uv/)** (recommended for this repo: `uv sync`, `uv run …`)
- [ ] Docker Desktop or Docker Engine
- [ ] VS Code (or Cursor)
- [ ] Terraform CLI
- [ ] AWS CLI
- [ ] Node.js (optional; helpers or frontend)
- [ ] Postman or `curl` for API testing

**Notes:** Terraform is the standard IaC path for repeatable infrastructure. n8n is easiest locally via Docker (see n8n self-hosting and AI workflow docs).

### 3.3 Concepts to be comfortable with

- Python packaging; **uv** for envs and runs (`uv sync`, `uv run`)
- REST APIs
- Basic Docker
- JSON
- Environment variables and secrets
- Git branching and commits
- Prompting and tool-calling
- Basic cloud networking (before deploy phases)

### 3.4 Target repository layout

```
autonomous-incident-response-agent/
├── execution.md
├── README.md
├── .env.example
├── docs/
│   ├── architecture/
│   └── decisions/
├── app/
│   ├── api/
│   ├── agent/
│   ├── rag/
│   ├── services/
│   └── models/
├── workflows/
│   └── n8n/
├── data/
│   ├── runbooks/           # SRE procedural corpus (RB-*); RAG retrieval
│   ├── incidents/          # Synthetic incident postmortems + sample-incident.md
│   ├── logs/               # Synthetic .log bundles + sample-log.md
│   └── knowledge_base/     # Supplementary ops docs (escalation, ownership, tiers)
├── infra/
│   └── terraform/
│       ├── modules/
│       └── envs/
│           ├── dev/
│           └── prod/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── evaluation/
└── docker/
```

### 3.5 Secrets template (`.env.example`)

Do not commit real secrets. Expected keys:

```env
# LLM (you have these today)
OPENAI_API_KEY=
OPENROUTER_API_KEY=

# Optional: OpenAI-compatible base URL when calling models via OpenRouter
# OPENAI_API_BASE=https://openrouter.ai/api/v1

# Cloud / integrations (add when you reach those phases)
AWS_REGION=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
SLACK_WEBHOOK_URL=
VECTOR_DB_API_KEY=
N8N_BASIC_AUTH_USER=
N8N_BASIC_AUTH_PASSWORD=

# Optional later
# ANTHROPIC_API_KEY=
```

### 3.6 AWS before starting?

**No** for Phase 1. Use AWS once local logic is stable enough to deserve deployment.

---

## 4. Macro stages

| Stage | Focus |
|--------|--------|
| **A — Local prototype** | Core incident triage logic locally. |
| **B — Integrated MVP** | Agent + RAG + n8n + UI as one system. |
| **C — Production** | Containerise, Terraform, AWS deploy, monitoring. |

---

## 5. Phases (recommended sequence)

### Phase 1 — Define the business problem

- [x] One-page product definition in `docs/decisions/problem-definition.md`
- **Deliverable:** Product boundary documented (no code required).

### Phase 2 — Incident knowledge and sample data

- [x] Runbooks, troubleshooting notes, postmortems, ownership, escalation matrix (examples)
- [x] Sample incident payloads: CPU saturation, memory leak, 5xx spike, DB connection exhaustion, K8s crash loop, disk full, SSL expiry, etc. (covered across `data/incidents/` and `data/logs/`)
- [x] Targets: `data/knowledge_base/`, `data/incidents/`, `data/logs/`, `data/runbooks/`
- **Deliverable:** ≥10 runbook docs, ≥20 incident examples, ≥5 realistic log files

**Phase 2 inventory (verified):**

| Asset | Location | Count |
|-------|-----------|------:|
| Runbooks | `data/runbooks/*.md` | 11 |
| Incident write-ups | `data/incidents/incident-*.md` | 20 |
| Incident template / catalog | `data/incidents/sample-incident.md` | 1 |
| Log bundles | `data/logs/*.log` | 21 |
| Log conventions | `data/logs/sample-log.md` | 1 |
| Knowledge base (supplementary) | `data/knowledge_base/*.md` | 5 (README + 4 guides) |

**Ingestion note for Phase 3:** Index `data/runbooks/`, `data/incidents/incident-*.md`, `data/logs/*.log`, and `data/knowledge_base/*.md` (see root `README.md` and `data/README.md`).


### Phase 3 — Local RAG foundation

- [x] Under `app/rag/`: loader, chunking, embeddings, index, retrieval
- [x] Start simple (FAISS); migrate to managed vector store if needed (later)
- **Deliverable:** Script or endpoint: e.g. query _“High CPU on payment-api in production”_ → relevant runbook excerpts **(verified via CLI)**

### Phase 4 — Reasoning agent (LangGraph)

- [x] Triage agent: interpret → retrieve → reason → structured output
- [x] **Output schema (JSON):** `incident_summary`, `severity` (LOW|MEDIUM|HIGH|CRITICAL), `likely_root_cause`, `recommended_actions[]`, `escalate`, `confidence`
- [x] **Nodes:** input normalisation → retrieval → analysis → decision → output formatter
- **Deliverable:** Local CLI: incident JSON → structured triage JSON (`uv run triage -f examples/sample_incident_payload.json`)

### Phase 5 — API layer (FastAPI)

- [x] `POST /triage`, `POST /ingest-incident`, `GET /health`, `GET /version`
- [x] `/triage`: payload → retrieval → agent → structured response
- **Deliverable:** Local backend verified with curl/Postman (`uv run serve-api`, see root `README.md`)

### Phase 6 — n8n execution layer

- [x] Run n8n locally (Docker) — `docker-compose.n8n.yml`
- [x] **Workflow `incident-triage-escalation`:** webhook in → if CRITICAL → Slack + log → status out
- [x] **Workflow `incident-ticket-creation`:** triage in → if `escalate` → ticket payload → mock Jira-style API → ticket ref
- **Deliverable:** Two workflows callable via test endpoints (see `workflows/n8n/README.md`)

### Phase 7 — Minimal UI

- [x] Gradio: paste payload → structured triage view, severity/confidence UX, feedback + `triage_id`
- **Deliverable:** UI at `/ui` on same FastAPI process (`uv sync --extra ui`, `ENABLE_GRADIO_UI`)

### Phase 8 — Evaluation

- [x] Gold set (8 seed cases in `data/eval/gold.jsonl`; expand toward 20–30)
- [x] Metrics: classification, optional retrieval checks, evidence-grounding heuristic, latency (mean / p95)
- **Deliverable:** `uv run triage-eval` + Markdown report (`--out`)

### Phase 9 — Containerise

- [x] Dockerise backend, UI, n8n, optional vector/DB
- **Deliverable:** `docker-compose.yml` runs full stack locally

### Phase 10 — AWS with Terraform

- [x] Layout: `infra/terraform/modules/` (vpc, ecs, alb, iam, ecr, monitoring) + `envs/dev`, `envs/prod`
- [x] Lean first cut: VPC, subnets, SGs, ECR, ECS cluster/services, ALB, IAM, CloudWatch logs, SSM parameters; **ECS on Fargate**
- **Deliverable:** `terraform init`, `plan`, `apply` for dev *(IaC in repo; run `apply` in your AWS account — see `infra/terraform/README.md`)*

### Phase 11 — Deploy to AWS

- [x] Push images to ECR; run services *(script + runbook; execute in your account after `terraform apply`)*
- **Deliverable:** Usable URL (dev/prod separated from day one) — ALB DNS from Terraform outputs; `curl …/health` after push + rollout

### Phase 12 — Presentation triage UI (Next.js)

- [x] Next.js app router console: incident JSON, `POST /triage`, evidence, feedback; static export to S3 (optional CloudFront)
- [x] Terraform `frontend_static_cdn` + `cors_origins` / `CORS_ORIGINS` for browser → ALB API
- **Deliverable:** [`frontend/README.md`](frontend/README.md), deploy script, CORS verification script

### Phase 13 — Observability

- [ ] API latency, errors, tokens, workflow success, container logs, triage duration
- **Deliverable:** CloudWatch logs for services + at least one dashboard or alarm path

### Phase 14 — CI/CD

- [ ] GitHub Actions: lint, unit tests, eval subset, docker build, push ECR, deploy trigger (dev)
- **Deliverable:** Working workflow for dev

### Phase 15 — Extensions (optional)

- [ ] **A:** Slack incident intake
- [ ] **B:** Similar past incidents before remediation
- [ ] **C:** Structured reports for Jira/ServiceNow-style systems
- [ ] **D:** Human approval for high-risk automation
- [ ] **E:** Cost/model routing (cheap vs strong models)

---

## 6. Milestone order (checklist)

Use this as the default execution order:

- [x] **Milestone 0** — Repo, tools, `.env.example`, folder structure *(workflows, tests, Docker, `infra/terraform` present)*
- [x] **Milestone 1** — Product problem and I/O definition
- [x] **Milestone 2** — Runbooks, sample incidents, logs
- [x] **Milestone 3** — RAG retrieval locally
- [x] **Milestone 4** — LangGraph triage agent locally
- [x] **Milestone 5** — FastAPI endpoints
- [x] **Milestone 6** — n8n escalation workflow
- [x] **Milestone 7** — Gradio UI (`app/ui`, `/ui`)
- [x] **Milestone 8** — Evaluation suite (`app/eval`, `data/eval/gold.jsonl`)
- [x] **Milestone 9** — Full docker-compose
- [x] **Milestone 10** — Terraform dev environment *(+ prod env root; apply when ready)*
- [x] **Milestone 11** — ECS Fargate deploy *(image push + `update-service`; see `docs/deploy/aws-ecs.md`)*
- [x] **Milestone 12** — Next.js triage UI *(S3/CloudFront, API CORS; see `frontend/README.md`)*
- [ ] **Milestone 13** — CloudWatch observability
- [ ] **Milestone 14** — CI/CD

---

## 7. Definition of done (portfolio / JD alignment)

At completion you should be able to demonstrate:

- LangChain / LangGraph agent design
- RAG pipeline (chunking, embeddings, vector search)
- n8n workflow orchestration
- Backend API engineering
- AWS deployment
- Terraform-based infrastructure
- Monitoring and operational maturity
- Credible business relevance (triage under pressure, consistent first response)

---

## 8. How to use this file

1. Keep **problem definition** and **sample runbooks** current as the source of truth for what “good” looks like.
2. Do not skip **Phase 2** data; retrieval quality depends on it.
3. Treat **Phase 13+** (observability, TLS, CI/CD) as the next slices after the API and hosted UI are wired.

---

*Last updated: 2026-04-02 — Phase 12 complete: Next.js triage console, S3/CloudFront static hosting, ECS `CORS_ORIGINS`. Next: Phase 13 (observability).*
