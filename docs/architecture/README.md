# Architecture

High-level view of the **Autonomous DevOps Incident Response System**: alerts and users → core incident stack (API, LLM agent, RAG, response API) → n8n automation → AWS deployment, with observability feeding back.

## Diagram

![Autonomous DevOps Incident Response System — logical architecture](../../architectural-diagram.png)

*Source file (repo root): [`architectural-diagram.png`](../../architectural-diagram.png)*

## How this maps to the repo

| Diagram area | Implementation (by phase) |
|--------------|---------------------------|
| Monitoring / Slack / engineer ingress | Phase 5–6: FastAPI + n8n webhooks; Slack via n8n when CRITICAL |
| API Gateway & Webhook | Phase 5: `app/api/` · Phase 6: `workflows/n8n/` + `docker-compose.n8n.yml` |
| LLM Agent (LangChain / LangGraph) | Phase 4: `app/agent/` |
| RAG + logs & runbooks + vector store | Phase 3: `app/rag/` + corpora under `data/` and `data/runbooks/` |
| Response API | Phase 5: structured triage JSON over HTTP |
| n8n workflows | Phase 6: `workflows/n8n/` |
| AWS (ECS Fargate, S3/CloudFront UI, CloudWatch, etc.) | Phases 9–13: `Dockerfile`, `infra/terraform/` (Fargate API, static UI, CloudWatch dashboard/alarms + triage log metrics) |

Aligns with the five layers in my `execution.md` (ingress, reasoning, retrieval, workflow, deployment), if present.

**Maintainer:** Oluwatosin Jegede
