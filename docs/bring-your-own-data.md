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

## Legacy layout

If `RAG_CORPUS_ROOT` is set, that path wins. If it is unset and workspace `data/` has no corpus files, the app falls back to repo-root `data/` (see `app/rag/config.py`).
