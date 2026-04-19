# Workspaces (Version 2)

Runtime corpus and vector index for the active **`WORKSPACE_ID`** (default: `default`) live under:

```text
workspaces/<WORKSPACE_ID>/
├── data/          # runbooks, incidents, logs, knowledge_base (optional mirror of repo data/)
├── index/         # FAISS bundle (gitignored); default when RAG_INDEX_DIR is unset
└── config/        # reserved for workspace-scoped overrides
```

If `workspaces/.../data` has no corpus files yet, the app falls back to repository **`data/`** for runbooks/incidents/logs so existing clones keep working.

Override paths with **`RAG_CORPUS_ROOT`** and **`RAG_INDEX_DIR`** when needed (see root `.env.example`).

## Docker Compose

Local [`docker-compose.yml`](../docker-compose.yml) mounts this directory at **`/app/workspaces`**. Populate **`workspaces/<WORKSPACE_ID>/data/`** on the host, run **`./scripts/product/rebuild-index.sh`** (or `uv run product-build-index`), then **`./scripts/product/start.sh`**. The default stack does **not** start n8n; use **`docker compose --profile automation up -d --build`** when you need it.
