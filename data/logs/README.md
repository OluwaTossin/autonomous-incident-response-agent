# `data/logs/`

Synthetic **log bundles** (`.log`) for triage/RAG practice, plus [`sample-log.md`](sample-log.md) (format conventions and catalog linking logs → incidents → runbooks).

## Phase 3 ingestion

- **`*.log`** — Plain-text narrative-style lines (not raw ALB/CloudWatch exports; see `sample-log.md`).
- **`sample-log.md`** — Documentation; optional to embed.

## Phase 5 API audit (local only)

- **`triage_outputs.jsonl`** — One JSON object per line (`timestamp`, `input`, `output`) for each `POST /triage`. Created automatically; **gitignored** (may contain sensitive alert text). Override path with `TRIAGE_AUDIT_JSONL`; disable with `TRIAGE_AUDIT_DISABLE=1`.

## Related

- Incidents: [`../incidents/`](../incidents/)
- Runbooks: [`../runbooks/`](../runbooks/)
