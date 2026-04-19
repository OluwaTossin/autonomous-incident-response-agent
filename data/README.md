# Data directory

Runtime **JSONL logs** (audit, n8n, triage feedback) and the **evaluation** gold set live here. The **RAG runbook/incident/log corpus** moved to **[`sample_data/default_demo/`](../sample_data/default_demo/)** in Version 2.6 so demos do not overwrite operator workspaces.

## Layout

| Subfolder | Role |
|-----------|------|
| **`eval/`** | Gold JSONL + README (`gold.jsonl` for `uv run triage-eval`). |
| **`logs/`** | Optional local JSONL outputs (`triage_outputs.jsonl`, etc.; see root `.gitignore`). |

## RAG corpus location

- **Demo / default:** `AIRA_DATA_MODE=demo` → empty workspace falls back to **`sample_data/default_demo/`**.
- **User-only:** `AIRA_DATA_MODE=user` → corpus is only **`workspaces/<WORKSPACE_ID>/data/`** (or `RAG_CORPUS_ROOT` if set).

See [`sample_data/README.md`](../sample_data/README.md) and [`docs/bring-your-own-data.md`](../docs/bring-your-own-data.md).
