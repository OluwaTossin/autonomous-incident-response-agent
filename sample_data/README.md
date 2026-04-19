# Sample data (Version 2.6)

Bundled **synthetic** corpus for demos, CI, and fresh clones. Not for production secrets or live telemetry.

| Path | Role |
|------|------|
| **`default_demo/`** | Default demo bundle: `runbooks/`, `incidents/`, `logs/`, `knowledge_base/` (same layout as operator workspaces). |

When **`AIRA_DATA_MODE=demo`** (default) and the active workspace `data/` has no corpus files yet, RAG resolves the corpus root here instead of mixing demo files into `workspaces/<id>/data/`.

Set **`AIRA_DATA_MODE=user`** for strict workspace-only corpus (empty workspace → operational corpus is empty aside from repo `docs/decisions/` merged by the loader).
