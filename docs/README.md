# Product documentation (Version 2)

Start here for **install → configure → data → index → operate**. Build history and deep architecture live elsewhere (see table below).

| Doc | Audience | Purpose |
|-----|----------|---------|
| [**Installation**](installation.md) | Operators | Prerequisites, clone, `.env`, first index, Docker Compose |
| [**Configuration**](configuration.md) | Operators | Precedence (`config.yaml` vs env), keys, workspace, rate limits |
| [**Bring your own data**](bring-your-own-data.md) | Operators | Workspace layout, demo vs user mode, CLI, admin upload |
| [**Reindexing**](reindexing.md) | Operators | When and how to rebuild the FAISS bundle (CLI + API) |
| [**Security**](security.md) | Operators + deployers | Keys, TLS/proxy, Compose vs ECS, threat model, non-goals |
| [**Troubleshooting**](troubleshooting.md) | Everyone | Common failures (CORS, auth, index, Docker UID) |
| [**Operator UI walkthrough**](operator-ui-walkthrough.md) | Demos / trainers | Triage vs Setup vs Configuration order, step-by-step, sample demo scripts |

**Also useful:** [`../README.md`](../README.md) (repo landing), [`../frontend/README.md`](../frontend/README.md) (Next.js), [`../workspaces/README.md`](../workspaces/README.md) (paths), deploy docs under [`deploy/`](deploy/) (including **[`deploy/aws-ecs.md`](deploy/aws-ecs.md)** — Git vs **`backend.hcl`**, clone + local vs cloud), **[`../infra/terraform/README.md`](../infra/terraform/README.md)** (what is committed vs gitignored, greenfield ECR order), Version 1 narrative in [`build-journey/execution-v1.md`](build-journey/execution-v1.md).
