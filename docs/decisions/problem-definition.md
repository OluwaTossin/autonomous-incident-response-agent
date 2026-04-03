# Problem definition — Autonomous incident triage

**Status:** Draft (Phase 1)  
**Owner:** Oluwatosin Jegede  
**Review cadence:** Update when scope, environments, or escalation policy changes.

---

## One-line objective

When an operational incident alert occurs, the system shall produce a **first-response triage output in under 30 seconds** (wall-clock, under normal local or deployed conditions), so responders spend less time gathering context and more time fixing the right thing.

---

## Who uses it

| Persona | How they use it |
|---------|------------------|
| **DevOps engineer** | First touch on alerts; validates or overrides triage before deeper debug. |
| **SRE / platform engineer** | Consistent severity and escalation hints across services and environments. |
| **On-call engineer** | Fast summary, likely cause, and next actions when paged overnight. |

The system **assists** humans; it does not replace ownership, change management, or final escalation authority unless explicitly wired to automation with guardrails (out of scope for the initial prototype).

---

## What triggers it

- **Primary:** An **incident alert** from monitoring (e.g. PagerDuty-style payload, Prometheus alert, or custom webhook).
- **Secondary:** A **log- or metric-derived event** represented as a structured “incident” object (same schema as alerts for consistency).
- **Demo / lab:** Manual submission via API or UI using the same payload shape.

---

## Inputs (minimum contract)

The ingress layer shall accept a structured incident payload. **Minimum fields:**

| Field | Description |
|-------|-------------|
| **Alert title** | Short human-readable title from the alerting system. |
| **Service name** | Logical service identifier (e.g. `payment-api`). |
| **Environment** | e.g. `dev`, `staging`, `production`. |
| **Logs** | Relevant log excerpts or references (text blob or structured lines). |
| **Metric summary** | Key numbers or thresholds breached (CPU, error rate, latency, etc.). |
| **Time of occurrence** | When the condition was detected (ISO 8601 recommended). |

**Optional (recommended as the product matures):** runbook hints, trace IDs, deployment version, region, owning team, links to dashboards.

---

## Outputs (required)

The system shall return a **structured triage result** suitable for display, logging, and downstream workflow (e.g. n8n):

| Output | Purpose |
|--------|---------|
| **Summary of incident** | Plain-language description of what is happening. |
| **Severity class** | `LOW` \| `MEDIUM` \| `HIGH` \| `CRITICAL` aligned to org definitions (document mapping in runbooks). |
| **Likely root cause** | Hypothesis grounded in retrieved context; must be labeled as hypothesis, not fact. |
| **Recommended remediation** | Ordered, actionable steps (can reference runbook IDs or titles). |
| **Escalation decision** | Boolean or enum: whether to escalate (page next tier, leadership, vendor, etc.). |
| **Evidence attribution** *(extended)* | List of `{ type, source, reason }` tying conclusions to corpus files and payload slices. |
| **Contradiction / multi-cause** *(extended)* | Optional summary when signals imply more than one primary failure mode. |
| **Timeline** *(extended)* | Ordered event strings (relative or ISO) for temporal orientation. |

The canonical Pydantic schema lives in [`app/models/triage.py`](../../app/models/triage.py). Product framing and roadmap for the extended fields are in [`capabilities-and-roadmap.md`](capabilities-and-roadmap.md). This document defines **semantic** requirements; keep a private root `execution.md` for personal phase checklists if you use one.

---

## Business pain addressed

| Pain | How this helps |
|------|----------------|
| **Slow first triage** | Sub-30s structured output reduces time to “what is it and how bad.” |
| **Inconsistent first response** | Same inputs lead to comparable severity framing and suggested checks. |
| **Tribal knowledge** | Runbooks and notes are retrieved at decision time instead of living only in chat history. |
| **Alert fatigue** | Quick severity + escalation hint supports prioritisation when many alerts fire. |

---

## Explicit non-goals (initial version)

- Fully automated remediation without human review (unless later gated in your local execution plan).
- Guaranteed root-cause correctness (LLM + RAG produce **hypotheses**; humans verify).
- Replacement of the authoritative monitoring or ticketing system of record.

---

## Success signals (how we know it is working)

- Responders report **faster orientation** on synthetic and real-style incidents.
- Retrieved runbook excerpts are **relevant** to the alert type (measured in Phase 8).
- Severity and escalation align with a **gold evaluation set** often enough to trust the system for first pass (thresholds to be set in evaluation phase).

---

## References

- Sample operational procedure: `data/runbooks/sample-runbook-01.md`
- Build order / phases: root [`execution.md`](../../execution.md) or this repo’s [`README.md`](../../README.md)
