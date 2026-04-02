# Evaluation gold set (Phase 8)

## Format (`gold.jsonl`)

One JSON object per line (JSONL). Lines starting with `#` or empty lines are skipped.

| Field | Meaning |
|-------|---------|
| `id` | Stable case id (used in reports). |
| `incident` | Same object you would send to `POST /triage`. |
| `expect` | Optional assertions (all omitted → no checks beyond “no graph error”). |

### `expect` fields (all optional)

| Field | Assertion |
|-------|------------|
| `severity` | Exact severity (case-insensitive). |
| `severity_any_of` | Actual severity must be one of these. |
| `escalate` | Must match `escalate` boolean. |
| `min_actions` | At least this many `recommended_actions`. |
| `summary_contains_all` | Each phrase must appear in `incident_summary` (case-insensitive). |
| `root_cause_contains_any` | At least one phrase in `likely_root_cause`. |
| `retrieval_source_contains_any` | At least one retrieval hit `source` contains one substring (needs built RAG index). |
| `min_top_retrieval_score` | Max hit `score` must be ≥ this (needs index + embeddings). |

## Run

Requires `.env` (API keys), built RAG index (same as triage CLI), and network for the LLM.

```bash
# Does not append triage audit lines by default
uv run triage-eval

# Markdown under data/eval/reports/ is gitignored (only .gitkeep is tracked)
# Custom gold file + Markdown report
uv run triage-eval --gold data/eval/gold.jsonl --out data/eval/reports/latest.md

# Keep audit logging on (append to triage_outputs.jsonl)
uv run triage-eval --keep-audit --out data/eval/reports/latest.md
```

Exit code **0** if all cases pass, **1** if any fail, **2** if gold file missing.

## Growing the set

Target **20–30** incidents for regression confidence (`execution.md`). Copy a line in `gold.jsonl`, change `id` and `incident`, and set `expect` loosely at first (e.g. `severity_any_of` only), then tighten after you see stable model behavior.

## Metrics (report)

- **Classification:** severity / escalate / action count vs gold.
- **Latency:** mean and p95 wall time per case (includes LLM + retrieval).
- **Retrieval:** optional substring / score checks when you enable them in `expect`.
- **Evidence grounding:** share of evidence `source` strings overlapping retrieval hit paths (heuristic, not a full hallucination detector).
