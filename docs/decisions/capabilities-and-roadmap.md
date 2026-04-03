# Capabilities and roadmap — accurate classification

**Status:** Living document  
**Owner:** Oluwatosin Jegede  
**Companion:** [`problem-definition.md`](problem-definition.md) (semantic requirements)

---

## What I have built (accurate classification)

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

I'm at roughly **~90% completeness** for a strong local prototype. The remaining **~10%** is what separates a **strong project** from an **elite system** in reviews and production trust.

### 1. Evidence attribution (critical upgrade)

Today the model *infers*; it does not yet *prove* provenance in a machine-readable way. I want explicit linkage:

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

**Implementation:** [`app/agent/signal_reasoning.py`](../../app/agent/signal_reasoning.py) builds one `evidence` row per retrieved **source** (merged chunk scores). [`node_enrich_triage`](../../app/agent/nodes.py) prepends those rows and dedupes against the LLM’s payload-specific evidence. Schema: [`app/models/triage.py`](../../app/models/triage.py).

### 2. Contradiction handling

What happens when **logs say CPU high** but **DB connections are also exhausted**? An elite system should surface tension explicitly, for example:

> “Conflicting signals detected. Possible multi-cause incident.”

**Implementation:** Heuristic multi-family detection in `detect_conflicting_signals()` (CPU vs DB pool, memory, disk, network/TLS, etc.) runs on the incident payload; if the LLM left `conflicting_signals_summary` empty, the enrich step fills it. Otherwise the model’s wording is kept.

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

**Implementation:** `build_programmatic_timeline()` anchors on `time_of_occurrence` / `timestamp` / `detected_at`, extracts ISO-like times and `T+2m`-style markers from logs, then `merge_timelines()` prepends those before LLM timeline lines (deduped).

---

## Summary

| Theme | Field / artifact | Status |
|--------|------------------|--------|
| Attribution | `evidence[]` | Programmatic RAG rows + LLM payload rows (deduped) |
| Contradictions | `conflicting_signals_summary` | Heuristics + LLM (LLM wins if non-empty) |
| Temporality | `timeline[]` | Programmatic extraction + LLM (merged, deduped) |

Next hardening steps: evaluation harness with gold attributions, richer parsers (deploy markers, trace IDs), and Phase 5 API (`POST /triage`).
