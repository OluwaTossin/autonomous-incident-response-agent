# Capabilities and roadmap — accurate classification

**Status:** Living document  
**Owner:** Oluwatosin Jegede  
**Companion:** [`problem-definition.md`](problem-definition.md) (semantic requirements)

---

## What you have built (accurate classification)

Name it correctly:

**An AI-powered incident triage and diagnosis engine.**

More specifically, the codebase today implements:

| Capability | Role in the system |
|------------|-------------------|
| **RAG-based knowledge retrieval** | FAISS + embeddings over runbooks, incidents, logs, knowledge base, and decision docs. |
| **Multi-source evidence fusion** | Single prompt combines normalized alert payload with top‑K retrieved chunks (mixed doc types). |
| **Heuristic + LLM reasoning** | Structured output schema, severity/escalation guardrails, hypothesis-style root cause. |
| **Action recommendation layer** | Ordered `recommended_actions` plus `escalate` and `confidence`. |

This is directly aligned with how **AIOps platforms**, **SRE copilots**, and **internal reliability tooling** at large tech companies frame first-response assistance: fast orientation, grounded suggestions, human-in-the-loop.

---

## What is still missing (the final ~10%)

You are at roughly **~90% completeness** for a strong local prototype. The remaining **~10%** is what separates a **strong project** from an **elite system** in reviews and production trust.

### 1. Evidence attribution (critical upgrade)

Today the model *infers*; it does not yet *prove* provenance in a machine-readable way. You want explicit linkage:

> “This conclusion came from **this** log + **this** incident (and optionally **this** runbook).”

Target shape (illustrative):

```json
"evidence": [
  {
    "type": "log",
    "source": "noisy-neighbor-node-contention.log",
    "reason": "Node CPU spike and throttling"
  },
  {
    "type": "incident",
    "source": "incident-18-noisy-neighbor-resource-contention.md",
    "reason": "Historical similarity"
  }
]
```

This builds **trust**, **explainability**, and **interview credibility**.

**Implementation:** Partially addressed in code — see `EvidenceItem` and `evidence` on `TriageOutput` in [`app/models/triage.py`](../../app/models/triage.py). Retrieval snippets expose `source=`; the model should cite those filenames/paths and ingest excerpts where applicable.

### 2. Contradiction handling

What happens when **logs say CPU high** but **DB connections are also exhausted**? An elite system should surface tension explicitly, for example:

> “Conflicting signals detected. Possible multi-cause incident.”

**Implementation:** Use `conflicting_signals_summary` on `TriageOutput` when evidence pulls in different failure modes; leave `null` when signals align.

### 3. Time awareness

Real incidents are **temporal** (before deploy, after deploy, during spike). The engine should start tracking an ordered narrative, e.g.:

```json
"timeline": [
  "CPU spike at T+2m",
  "Latency spike at T+3m",
  "Errors at T+5m"
]
```

Use incident `time_of_occurrence` as anchor when absolute timestamps are unknown; prefer ISO timestamps when present in payload or logs.

**Implementation:** `timeline` on `TriageOutput` — list of short strings, ordered.

---

## Summary

| Theme | Field / artifact | Status |
|--------|------------------|--------|
| Attribution | `evidence[]` | Schema + prompts; tighten evals over time |
| Contradictions | `conflicting_signals_summary` | Schema + prompts |
| Temporality | `timeline[]` | Schema + prompts |

Next hardening steps: evaluation harness with gold attributions, API contract for Phase 5 (`POST /triage`), and optional automatic evidence pre-fill from retrieval metadata before the LLM pass.
