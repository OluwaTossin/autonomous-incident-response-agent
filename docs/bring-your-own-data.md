# Bring your own data (workspace contract)

Version 2 treats each tenant or environment as a **workspace** under `workspaces/<WORKSPACE_ID>/`. Operational files for RAG live in **`data/`** inside that workspace (not the legacy repo-root `data/` unless you set `RAG_CORPUS_ROOT`).

## Layout

Create:

```text
workspaces/<WORKSPACE_ID>/
  data/
    runbooks/        # *.md — procedures, playbooks
    incidents/       # *.md — narratives, postmortems
    logs/            # *.log (and related notes as *.md if you prefer)
    knowledge_base/  # *.md — ownership, tiers, glossary, …
  index/             # FAISS output from index build (gitignored by default)
```

`WORKSPACE_ID` must match `^[a-zA-Z0-9_-]{1,64}$`.

## What gets indexed

The loader globs the same patterns under the active corpus root (see `app/rag/loader.py`). In addition, design decisions under `docs/decisions/` in the repo are merged into the corpus when present.

Unsupported suffixes under `data/` (for example `.pdf` today) are **not** read by the indexer. `product-validate-workspace` warns about them so you can relocate or convert content.

## Product commands

After `uv sync --extra dev`:

| Command | Purpose |
|--------|---------|
| `uv run product-validate-workspace --workspace <id>` | Check layout and file conventions (`--strict` fails if there is no workspace corpus yet). |
| `uv run product-build-index --workspace <id>` | Set workspace-only corpus mode, validate, then run the same index pipeline as `rag-build`. Use `--dry-run` to validate only. |

These set `RAG_WORKSPACE_ONLY=1` for the build path so the corpus root is always `workspaces/<id>/data/` (created if missing). Pass through extra flags to the underlying builder, for example:

```bash
uv run product-build-index --workspace demo -- --chunk-size 800
```

## Admin HTTP API (ingestion)

With **`ADMIN_API_KEY`** set, the API exposes **`POST /admin/upload`** (multipart `category` + `file`), **`GET /admin/files`**, **`POST /admin/reindex`**, and **`GET /admin/index-status`** — all require header **`x-admin-api-key`**. See [`docs/security.md`](security.md).

## Docker Compose (local product)

The default [`docker-compose.yml`](../docker-compose.yml) bind-mounts **`./workspaces`** and **`./data`** into the API container and leaves **`RAG_INDEX_DIR`** empty so the index lives under `workspaces/<WORKSPACE_ID>/index/`. Build the index on the host before starting the stack, then run `./scripts/product/start.sh` (or `docker compose up -d --build`). **n8n** is behind the Compose profile **`automation`** — start it with `docker compose --profile automation up -d --build`.

The **Next.js** service is a static export; at image build time it receives **`NEXT_PUBLIC_API_BASE_URL`** pointed at `http://127.0.0.1:<COMPOSE_API_PORT>` so your browser can call the published API port from the same machine.

## Demo vs user corpus mode

Set **`AIRA_DATA_MODE`** in `.env` or `config.yaml`:

| Value | Behaviour when workspace `data/` has no corpus files |
|--------|--------------------------------------------------------|
| `demo` (default) | Use bundled **`sample_data/default_demo/`** (synthetic runbooks/incidents/logs). |
| `user` | Use only workspace **`data/`** (empty until you add files); no silent mixing of bundled sample into your tree. |

`RAG_CORPUS_ROOT` still overrides both when set (see `app/rag/config.py`).

## Legacy layout

Repo-root **`data/`** now holds **eval** assets and optional **runtime JSONL** logs; the RAG markdown corpus lives under **`sample_data/default_demo/`** for the default demo path.
