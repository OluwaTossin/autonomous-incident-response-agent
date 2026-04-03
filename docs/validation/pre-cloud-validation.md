# Pre-cloud validation (manual)

Run these **before** Terraform/ECS so behaviour is understood on a **real** stack (Docker or `uv run serve-api`), not only offline eval.

**Prerequisites:** `.env` with keys, built index (`uv run rag-build`), API reachable (`API_BASE`, e.g. `http://127.0.0.1:18080` for default Compose).

---

## Scenario 1 — True triage flow

### 1A. `POST /triage`

```bash
export API_BASE=http://127.0.0.1:18080   # or http://127.0.0.1:8000 for host uvicorn

curl -sS -X POST "$API_BASE/triage" \
  -H "Content-Type: application/json" \
  -d @examples/sample_incident_payload.json | jq .
```

**Review the JSON (human gate, not automated):**

| Check | What “good” looks like |
|--------|-------------------------|
| **Severity** | Matches blast radius in payload (prod payment CPU → usually HIGH/CRITICAL band, not LOW). |
| **likely_root_cause** | Hypothesis tied to logs/metrics; not a generic paragraph; mentions contradiction if signals conflict. |
| **recommended_actions** | Verifiable next steps (check X, scale Y, rollback Z), not “monitor” only. |
| **confidence** | Lower when evidence is thin; higher when payload + retrieval align (subjective judgment). |
| **evidence** | Non-empty; includes payload-backed rows; ideally corpus paths under `data/` when RAG hit. |
| **triage_id** | Present for audit/feedback join. |

Repeat with **2–3** incidents that matter for the release (from `data/eval/gold.jsonl` or custom JSON). Compare to **Phase 8** gold expectations only as a regression signal; this step is **qualitative**.

### 1B. n8n wiring

1. Import and **activate** `incident-triage-escalation` and `incident-ticket-creation` (see `workflows/n8n/README.md`).
2. Pipe triage output into webhooks:

```bash
curl -sS -X POST "$API_BASE/triage" \
  -H "Content-Type: application/json" \
  -d @examples/sample_incident_payload.json \
| curl -sS -X POST http://localhost:5678/webhook/ticket-creation \
  -H "Content-Type: application/json" -d @-
```

**Escalation / ticketing (determinism):**

- **Ticket workflow:** `escalate === true` → mock Jira path; else `not_escalated`. No randomness in n8n IF nodes — behaviour is **deterministic** given the triage JSON.
- **Escalation workflow:** `severity === CRITICAL` branches by numeric `confidence`. **Operational policy** in the API (non-prod dampening, prod payment bump) runs **before** the response leaves `/triage` — n8n sees the **final** severity/escalate. Validate that staging/dev payloads are not paged like prod when policy is expected to apply.

---

## Scenario 2 — Failure & resilience (not “correctness”)

The goal is **degraded behaviour**: no crash, explicit uncertainty, sane severity.

### 2A. RAG returns no / weak hits

**Option A — empty index (destructive to local index; backup first):**

```bash
mv .rag_index .rag_index.bak
mkdir -p .rag_index
# restart API, then POST /triage
# restore: rm -rf .rag_index && mv .rag_index.bak .rag_index
```

**Option B — query that rarely matches** (non-destructive): use an incident whose `alert_title`/`logs` are unrelated to the corpus.

**Expect:** retrieval errors or “no hits” handled without 500; summary/root cause may be weaker; **confidence** should often drop; evidence may be LLM-only.

### 2B. Noisy / ambiguous logs

Use rows tagged `ambiguous`, `mixed_signals`, or `misleading_alert` from `data/eval/gold.jsonl` (or craft similar). Paste one incident into `/triage` or Gradio.

**Expect:** `conflicting_signals_summary` or nuanced root cause; avoid false CRITICAL without customer impact.

### 2C. Incomplete payload

```bash
curl -sS -X POST "$API_BASE/triage" \
  -H "Content-Type: application/json" \
  -d '{"alert_title":"Service unhealthy","service_name":"x","environment":"staging"}' | jq .
```

**Expect:** 200 with structured output **or** 422 if validation rejects; no raw stack trace to client. Severity/escalate conservative for staging/thin evidence.

---

## Scenario 3 — Latency & container overhead

### Quick repeated timings

```bash
./scripts/benchmark_triage_latency.sh 5 examples/sample_incident_payload.json
# or
API_BASE=http://127.0.0.1:8000 N=10 ./scripts/benchmark_triage_latency.sh
```

**Compare:**

1. **Host:** `uv run serve-api` + same payload, same `N`.
2. **Docker:** `docker compose` API + same script with `API_BASE=http://127.0.0.1:18080`.

**Interpretation:** Wall time is dominated by **LLM + embeddings**, not CPU in the container. Expect **similar order of magnitude** host vs container; large gaps suggest network (API base URL wrong), cold start, or rate limits.

**Repeated calls:** Run `N=20` once; watch for throttling or rising latency (provider-side). This is the start of **SLO thinking** — capture mean/p95 and revisit after Phase 12 observability.

---

## Definition of done (this checklist)

- [ ] Scenario 1: at least **one** production-like triage passes a **human** quality bar for severity, root cause, and actions.
- [ ] Scenario 1: n8n **ticket** and **escalation** webhooks behave as expected for **CRITICAL** vs non-critical and **escalate** true/false.
- [ ] Scenario 2: empty/minimal RAG and thin payload do **not** take down the API; outputs reflect uncertainty where appropriate.
- [ ] Scenario 3: recorded **mean** (and optionally p95) for `/triage` on host vs Docker for the same payload.

When this is done, **Phase 8** can be treated as regression automation and **this doc** as pre-release smoke, then cloud cutover can proceed with clear baselines.
