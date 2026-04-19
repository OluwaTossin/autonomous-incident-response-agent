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
