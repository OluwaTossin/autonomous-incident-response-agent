# Reindexing

The **vector index** (FAISS + chunk metadata) must exist before **`POST /triage`** returns grounded evidence. Rebuild it whenever corpus files under the active workspace change meaningfully.

## Where the index lives

- **Default:** `workspaces/<WORKSPACE_ID>/index/` when **`RAG_INDEX_DIR`** is unset (Docker Compose and typical local use).
- **Override:** set **`RAG_INDEX_DIR`** to an absolute or repo-relative path (e.g. legacy `.rag_index` for some ECS images).

The index directory is usually **gitignored**; treat it as a build artifact.

## When to reindex

- After adding, editing, or removing files under **`workspaces/<WORKSPACE_ID>/data/`** (or after changing **`AIRA_DATA_MODE`** / corpus roots).
- After changing **chunking** or **embedding model** settings that affect vectors.
- Not required on every API or config tweak that does not touch corpus or embedding behaviour.

## How to reindex

### A. Product CLI (recommended on the host)

```bash
uv run product-build-index --workspace default
```

Validate layout first (optional):

```bash
uv run product-validate-workspace --workspace default
```

Dry run (validate only):

```bash
uv run product-build-index --workspace default -- --dry-run
```

Shell helper (repo root):

```bash
./scripts/product/rebuild-index.sh
```

### B. Legacy / compatibility

```bash
uv run rag-build
```

When **`RAG_INDEX_DIR`** is unset, output still targets the workspace index for the active **`WORKSPACE_ID`**.

### C. Operator UI or API (requires admin auth)

With **`ADMIN_API_KEY`** set:

1. **Next.js** → **Setup** → **Rebuild index**, or  
2. **`POST /admin/reindex`** with header **`x-admin-api-key`**.

This runs the same pipeline as the CLI **inside the API process** (synchronous; can take minutes). Only **one** reindex at a time per worker; a second overlapping call returns **409**. Rate limit: **`API_RATE_LIMIT_ADMIN_REINDEX`** (default `2/minute`) when limits are enabled — see [`security.md`](security.md).

## Docker Compose

Build the index **on the host** (or in a one-off container with the same mounts) before relying on triage in a fresh clone:

```bash
uv run product-build-index --workspace default
./scripts/product/start.sh
```

The API container mounts **`./workspaces`**; the index under `workspaces/<id>/index/` must exist or be built after first start.

## Related docs

- Workspace data contract: [`bring-your-own-data.md`](bring-your-own-data.md)  
- Installation: [`installation.md`](installation.md)  
- Security (admin key): [`security.md`](security.md)  
