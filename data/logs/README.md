# `data/logs/`

Synthetic **log bundles** (`.log`) for triage/RAG practice, plus [`sample-log.md`](sample-log.md) (format conventions and catalog linking logs → incidents → runbooks).

## Phase 3 ingestion

- **`*.log`** — Plain-text narrative-style lines (not raw ALB/CloudWatch exports; see `sample-log.md`).
- **`sample-log.md`** — Documentation; optional to embed.

## Phase 5 API audit (local only)

- **`triage_outputs.jsonl`** — One JSON object per line for each `POST /triage`: `timestamp`, `input`, `output`, **`retrieved_context`** (RAG block passed to the LLM), **`top_k_sources`** (ranked `source` / `doc_type` / `score`). **Gitignored**; may contain sensitive **client-supplied** payload text. See [`docs/decisions/triage-audit-validation.md`](../../docs/decisions/triage-audit-validation.md). Env: `TRIAGE_AUDIT_JSONL`, `TRIAGE_AUDIT_DISABLE`, `TRIAGE_AUDIT_MAX_RAG_CHARS`.
- **`n8n_workflow_events.jsonl`** — Optional lines from **`POST /n8n/workflow-log`** (Phase 6 triage-escalation workflow). **Gitignored**. Env: `N8N_WORKFLOW_LOG_JSONL`, `N8N_WORKFLOW_LOG_DISABLE`.

## Related

- Incidents: [`../incidents/`](../incidents/)
- Runbooks: [`../runbooks/`](../runbooks/)
