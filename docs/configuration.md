# Configuration

AIRA reads **non-secret** tuning from optional YAML and **secrets / overrides** from the process environment (including `.env` loaded by the app). This page summarizes precedence and the main knobs.

## Precedence

Later steps override earlier ones **for the same logical setting** (see `app/config/settings.py`):

1. **Defaults** in code  
2. **`CONFIG_YAML`** — optional file; keys are **UPPER_SNAKE** at the YAML root (see [`config.example.yaml`](../config.example.yaml))  
3. **Workspace operator overrides** — `workspaces/<WORKSPACE_ID>/config/operator_overrides.yaml` (merged after global YAML, before env)  
4. **Environment** (including `.env`) — **wins** over YAML and operator overrides for each variable that is set

Secrets (**`OPENAI_API_KEY`**, **`API_KEY`**, **`ADMIN_API_KEY`**, etc.) must live in **environment only**, not in `config.yaml`.

## Essential environment variables

| Variable | Role |
|----------|------|
| `OPENAI_API_KEY` / `OPENROUTER_API_KEY` | LLM + embeddings |
| `WORKSPACE_ID` | Active workspace (default `default`) |
| `WORKSPACES_ROOT` | Directory name or path for workspaces (default `workspaces`) |
| `AIRA_DATA_MODE` | `demo` (bundled sample when workspace empty) or `user` (workspace only) |
| `RAG_INDEX_DIR` | Empty → `workspaces/<id>/index/`; set to pin index elsewhere |
| `RAG_CORPUS_ROOT` | Optional corpus root override |
| `RAG_WORKSPACE_ONLY` | `1` forces corpus to workspace `data/` (product CLI sets this) |
| `API_KEY` | When set, requires `x-api-key` on triage and ingest |
| `ADMIN_API_KEY` | When set, enables `/admin/*` and requires `x-admin-api-key` |
| `CORS_ORIGINS` | Comma-separated browser origins for the API |
| `API_RATE_LIMIT_*` / `API_RATE_LIMIT_DISABLED` | Slowapi limits — see [`security.md`](security.md) |

Full list and comments: [`.env.example`](../.env.example).

## Optional `config.yaml`

1. Copy [`config.example.yaml`](../config.example.yaml) to e.g. `config.yaml`.  
2. Export `CONFIG_YAML=config.yaml` (path relative to repo root is fine).  
3. Use only **non-secret** keys (model names, `RAG_TOP_K`, `AIRA_DATA_MODE`, rate limit strings, etc.).

## Workspace operator overrides

The Next.js **Configuration** page (or **`PATCH /admin/operator-settings`**) can persist allowlisted fields to:

`workspaces/<WORKSPACE_ID>/config/operator_overrides.yaml`

Process **environment** still overrides those values when the same variable is set in `.env` or the container.

## Further reading

- Data layout and modes: [`bring-your-own-data.md`](bring-your-own-data.md)  
- Rebuild index after changes: [`reindexing.md`](reindexing.md)  
- Keys, TLS, Compose vs ECS: [`security.md`](security.md)  
