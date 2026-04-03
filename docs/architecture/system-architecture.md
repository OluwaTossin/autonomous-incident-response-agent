# System architecture

End-to-end view of the **Autonomous DevOps Incident Response Agent** as implemented through **Phases 1–14**: triage API, RAG, LangGraph, n8n, AWS (ECS, ALB, ECR, SSM), static UI, CloudWatch, and GitHub Actions.

## Single overview (PNG)

Exported from **[`architecture-overview.mmd`](architecture-overview.mmd)** (regenerate: `npx @mermaid-js/mermaid-cli -i architecture-overview.mmd -o architecture-overview.png` from this folder).

![Architecture overview — Phases 1–14](./architecture-overview.png)

---

Detailed breakdowns below: open this file in **GitHub** or **Cursor** (Mermaid preview), or paste blocks into [mermaid.live](https://mermaid.live) for SVG/PNG variants.

---

## 1. Five layers (product view)

Maps to the phased build in [`execution.md`](../../execution.md).

```mermaid
flowchart LR
  subgraph ingress["Ingress"]
    I[Alerts · UI · Webhooks]
  end
  subgraph reasoning["Reasoning"]
    R[LangGraph agent · LLM]
  end
  subgraph retrieval["Retrieval"]
    G[RAG · FAISS · data/ corpus]
  end
  subgraph workflow["Workflow"]
    N[n8n · Slack · mock Jira]
  end
  subgraph deploy["Deployment & ops"]
    A[Docker · ECS Fargate · Terraform]
    O[CloudWatch · CI/CD]
  end
  ingress --> reasoning
  retrieval --> reasoning
  reasoning --> workflow
  reasoning --> deploy
  workflow --> deploy
```

---

## 2. Logical components (runtime)

```mermaid
flowchart TB
  subgraph clients["Clients"]
    UI[Next.js static UI<br/>S3 / CloudFront]
    GR[Gradio /ui]
    CL[curl · CLI · integrations]
  end

  subgraph api["FastAPI app container"]
    EP[app/api · POST /triage · /ingest-incident]
    AG[app/agent · LangGraph pipeline]
    RK[app/rag · FAISS index]
    MD[app/models · Pydantic schemas]
    AU[Audit JSONL · triage_id]
    EV[app/eval · triage-eval]
  end

  subgraph data["Data & index"]
    CORP[data/runbooks · incidents · logs · knowledge_base]
    IDX[.rag_index baked in image]
  end

  subgraph external["External services"]
    OAI[OpenAI / compatible API<br/>embeddings + chat]
  end

  subgraph automation["Automation"]
    N8[n8n workflows<br/>escalation · ticketing webhooks]
  end

  UI --> EP
  GR --> EP
  CL --> EP
  CORP --> RK
  IDX --> RK
  EP --> AG
  RK --> AG
  AG --> OAI
  AG --> EP
  EP --> AU
  N8 --> EP
  EP --> N8
```

---

## 3. AWS topology (dev / prod)

```mermaid
flowchart TB
  subgraph users["Users & operators"]
    BR[Browser]
    GH[GitHub Actions]
  end

  subgraph aws["AWS account"]
    CF[CloudFront optional]
    S3[S3 static website / UI bucket]
    ALB[ALB HTTP :80]
    TG[Target group]
    ECS[ECS Fargate service · API task]
    ECR[ECR · API image digest-pinned]
    SSM[SSM Parameter Store · secrets]
    CW[CloudWatch Logs · dashboard · alarms · metric filters]
  end

  subgraph build["Build / ship"]
    DK[Docker build + rag index]
  end

  BR --> CF
  CF --> S3
  BR --> ALB
  ALB --> TG
  TG --> ECS
  ECS --> ECR
  SSM -.->|injects env at start| ECS
  ECS --> CW
  DK --> ECR
  GH -->|push image · optional deploy| ECR
  GH --> ECS
```

---

## 4. Triage request flow (happy path)

```mermaid
sequenceDiagram
  participant C as Client UI or n8n
  participant ALB as ALB
  participant API as FastAPI /triage
  participant RAG as RAG retrieve
  participant LG as LangGraph + LLM
  participant CW as CloudWatch Logs

  C->>ALB: POST JSON incident
  ALB->>API: forward
  API->>RAG: query FAISS
  RAG-->>API: chunks + sources
  API->>LG: structured triage
  LG-->>API: severity · actions · triage_id
  API->>CW: JSON triage_metrics line
  API-->>C: triage JSON
  Note over C: Optional: forward to n8n webhooks
```

---

## 5. CI / CD (GitHub Actions)

```mermaid
flowchart LR
  subgraph trigger["Triggers"]
    P[Push / PR to dev or main]
  end

  subgraph ci["CI workflow"]
    L[ruff]
    T[pytest]
    TF[terraform fmt + validate]
    FE[npm build frontend]
    DK[Docker build]
    EV[eval-smoke optional<br/>OPENAI_API_KEY]
  end

  subgraph cd["Optional deploy"]
    DP[Deploy API dev<br/>ECR push + ECS rollout]
  end

  P --> L
  P --> T
  P --> TF
  P --> FE
  P --> DK
  P --> EV
  P --> DP
```

---

## Repo map (quick reference)

| Area | Path |
|------|------|
| API & agent | `app/api/`, `app/agent/`, `app/models/` |
| RAG | `app/rag/`, corpora under `data/` |
| UIs | `app/ui/`, `frontend/` |
| n8n | `workflows/n8n/` |
| IaC | `infra/terraform/` · `envs/dev` · `envs/prod` · `bootstrap/` |
| Deploy scripts | `scripts/aws/push_api_to_ecr.sh`, `deploy_frontend_cdn.sh` |
| Workflows | `.github/workflows/ci.yml`, `deploy-dev.yml` |

---

**Maintainer:** Oluwatosin Jegede
