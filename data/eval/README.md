# Evaluation gold set (Phase 8)

## Format (`gold.jsonl`)

One JSON object per line (JSONL). Lines starting with `#` or empty lines are skipped.

| Field | Meaning |
|-------|---------|
| `id` | Stable case id (used in reports). |
| `incident` | Same object you would send to `POST /triage`. |
| `expect` | Optional assertions (all omitted → no checks beyond “no graph error”). |
| `tags` | Optional labels for humans (e.g. `ambiguous`, `misleading_alert`, `over_escalate_risk`); not used in pass/fail. |
| `notes` | Optional free text for eval readers; not asserted. |

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

# First N cases only (CI smoke, quick checks)
uv run triage-eval --limit 3

# Markdown under data/eval/reports/ is gitignored (only .gitkeep is tracked)
# Custom gold file + Markdown report
uv run triage-eval --gold data/eval/gold.jsonl --out data/eval/reports/latest.md

# Keep audit logging on (append to triage_outputs.jsonl)
uv run triage-eval --keep-audit --out data/eval/reports/latest.md
```

Exit code **0** if all cases pass, **1** if any fail, **2** if gold file missing.

## Current gold set

- **27** rows in `gold.jsonl`, covering CPU variants, DB, network, auth, disk, ambiguous/misleading signals, thin logs, and escalation traps (under/over).
- Regenerate from the canonical Python list (easier than hand-editing JSON):

```bash
python3 scripts/generate_eval_gold.py
```

Most rows enable **`summary_contains_all`**, **`root_cause_contains_any`**, **`retrieval_source_contains_any`** (`data/`), and **`min_top_retrieval_score`** (0.05) so reports show real values for `summary_keywords_ok`, `root_cause_hint_ok`, and `retrieval_source_ok` instead of `None`. Keywords are chosen to match **incident text and normal operator paraphrases** (e.g. pool/connection vs literal “database”). **`root_cause_contains_any`** is satisfied if **any** listed phrase appears (OR). Tune further if your model’s vocabulary still drifts.

## Growing the set

Add cases in `scripts/generate_eval_gold.py`, re-run the script, then commit `data/eval/gold.jsonl`. Start loose (`severity_any_of` only), then tighten once behavior is stable.

## Metrics (report)

- **Classification:** severity / escalate / action count vs gold.
- **Latency:** mean and p95 wall time per case (includes LLM + retrieval).
- **Retrieval:** optional substring / score checks when you enable them in `expect`.
- **Evidence grounding:** share of evidence `source` strings overlapping retrieval hit paths (heuristic, not a full hallucination detector).
