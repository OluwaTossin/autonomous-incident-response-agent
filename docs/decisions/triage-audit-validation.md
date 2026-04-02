# Triage audit log — validation & next steps

**Purpose:** Verify `data/logs/triage_outputs.jsonl` (or `TRIAGE_AUDIT_JSONL`) before relying on it for Phase 6+ (n8n, evaluation).

---

## 1. Run multiple triage calls

Restart the API without `TRIAGE_AUDIT_DISABLE`, then:

```bash
curl -s -X POST http://127.0.0.1:8000/triage -H "Content-Type: application/json" \
  -d @examples/sample_incident_payload.json >/dev/null
# repeat with varied payloads or the same payload
```

**Inspect the last N lines** (each line is one JSON object — `python3 -m json.tool` on `tail -n 5` as a single stdin is invalid):

```bash
tail -n 5 data/logs/triage_outputs.jsonl | while IFS= read -r line; do
  echo "$line" | python3 -m json.tool
  echo "---"
done
```

Or:

```bash
python3 -c "
import json, sys
for line in open('data/logs/triage_outputs.jsonl'):
    line = line.strip()
    if not line:
        continue
    print(json.dumps(json.loads(line), indent=2))
    print('---')
" | tail -n 80
```

---

## 2. Structural consistency

For each record, confirm:

| Field | Expectation |
|--------|-------------|
| `timestamp` | ISO-8601 UTC string |
| `input` | Object (incident payload as sent) |
| `output` | Triage object: `incident_summary`, `severity`, `likely_root_cause`, `recommended_actions`, `escalate`, `confidence`, `evidence`, `conflicting_signals_summary`, `timeline` |
| `retrieved_context` | String (RAG block shown to the LLM; may be truncated — see `TRIAGE_AUDIT_MAX_RAG_CHARS`) |
| `top_k_sources` | Array of `{source, doc_type, score, chunk_index}` sorted by `score` descending |

On errors, `output` may include an `error` key and empty/minimal fields — still one line per request.

Check for unexpected `null` only where the schema allows (e.g. `conflicting_signals_summary` may be `null`).

---

## 3. Leakage (sensitivity)

The audit file **does not** add API keys or tokens from server env vars. It **does** copy **whatever the client sends** in `input` (and whatever the model returns in `output`). If callers paste secrets into `logs` or `metric_summary`, those will appear.

**Mitigations:**

- Keep the file **gitignored** (already).
- Restrict filesystem permissions on shared hosts.
- Add gateway redaction before `POST /triage` in production.
- Never send bearer tokens or raw credentials in the incident JSON.

---

## 4. Evaluation roadmap (inputs + outputs + time)

With `timestamp`, `input`, and `output`, you can add a parallel **gold** dataset, e.g.:

```json
{ "incident_id": "...", "expected_severity": "HIGH", "expected_escalate": true }
```

Then offline scripts can join on payload hash or id and compute **expected vs actual** severity, escalation, or action overlap — accuracy, regressions, and prompt/index changes.

---

## 5. RAG debugging

`retrieved_context` and `top_k_sources` exist so you can answer:

- What did retrieval return for this failure?
- Did the wrong doc rank high?
- Is the context truncated?

Tune retrieval, chunking, or query construction using these fields without re-running the full graph.
