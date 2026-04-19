"""LangGraph nodes: normalize → retrieve → analyze → decision → format."""

from __future__ import annotations

from typing import Any, TypedDict

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from app.agent.llm_usage import aggregate_llm_usage
from app.agent.operational_policy import apply_operational_policy
from app.agent.prompts import TRIAGE_SYSTEM
from app.agent.signal_reasoning import (
    build_programmatic_timeline,
    detect_conflicting_signals,
    evidence_from_retrieval_dicts,
    merge_evidence_lists,
    merge_timelines,
)
from app.models.incident import IncidentPayload
from app.models.triage import TriageOutput
from app.config import get_settings
from app.rag.retrieve import RetrievalHit, retrieve


class TriageState(TypedDict, total=False):
    incident: dict[str, Any]
    normalized_narrative: str
    retrieval_query: str
    rag_context: str
    retrieval_hits: list[dict[str, Any]]
    draft: dict[str, Any]
    result: dict[str, Any]
    error: str
    llm_usage: dict[str, Any]


def _pick(raw: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = raw.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def parse_incident_payload(raw: dict[str, Any]) -> IncidentPayload:
    merged = dict(raw)
    if title := _pick(raw, "alert_title", "alertTitle", "title"):
        merged["alert_title"] = title
    if svc := _pick(raw, "service_name", "serviceName", "service"):
        merged["service_name"] = svc
    if env := _pick(raw, "environment", "env"):
        merged["environment"] = env
    if logs := _pick(raw, "logs", "log_excerpt", "logExcerpt"):
        merged["logs"] = logs
    if met := _pick(raw, "metric_summary", "metricSummary", "metrics"):
        merged["metric_summary"] = met
    if t := _pick(raw, "time_of_occurrence", "timeOfOccurrence", "timestamp", "detected_at"):
        merged["time_of_occurrence"] = t
    return IncidentPayload.model_validate(merged)


def node_normalize_input(state: TriageState) -> dict[str, Any]:
    raw = state.get("incident") or {}
    if not isinstance(raw, dict):
        return {"error": "incident must be a JSON object"}
    try:
        payload = parse_incident_payload(raw)
    except ValidationError as e:
        return {"error": f"Invalid incident payload: {e}"}

    lines = [
        f"**Alert title:** {payload.alert_title or '(none)'}",
        f"**Service:** {payload.service_name or '(none)'}",
        f"**Environment:** {payload.environment or '(none)'}",
        f"**Time:** {payload.time_of_occurrence or '(none)'}",
        f"**Metric summary:** {payload.metric_summary or '(none)'}",
        f"**Logs / excerpts:**\n{payload.logs or '(none)'}",
    ]
    narrative = "\n".join(lines)
    rq_parts = [
        payload.alert_title,
        payload.service_name,
        payload.environment,
        payload.metric_summary,
        (payload.logs or "")[:400],
    ]
    retrieval_query = " ".join(p for p in rq_parts if p).strip() or "incident triage"
    return {
        "normalized_narrative": narrative,
        "retrieval_query": retrieval_query,
        "incident": payload.model_dump(mode="json"),
    }


def _hit_to_state_dict(h: RetrievalHit) -> dict[str, Any]:
    return {
        "score": h.score,
        "source": h.source,
        "doc_type": h.doc_type,
        "chunk_index": h.chunk_index,
    }


def node_retrieval(state: TriageState) -> dict[str, Any]:
    if state.get("error"):
        return {}
    q = state.get("retrieval_query") or ""
    try:
        hits = retrieve(q, top_k=get_settings().rag_top_k)
    except Exception as e:
        return {
            "rag_context": (
                f"(Vector retrieval failed — build index with "
                f"`uv run python -m app.rag.cli build-index`. Error: {e})"
            ),
            "retrieval_hits": [],
        }
    if not hits:
        return {
            "rag_context": "(No retrieval hits; index may be empty or query mismatched.)",
            "retrieval_hits": [],
        }
    blocks = []
    for i, h in enumerate(hits, 1):
        blocks.append(
            f"[{i}] score={h.score:.3f} type={h.doc_type} source={h.source}\n{h.text}"
        )
    return {
        "rag_context": "\n\n---\n\n".join(blocks),
        "retrieval_hits": [_hit_to_state_dict(h) for h in hits],
    }


def _chat_model() -> ChatOpenAI:
    s = get_settings()
    kwargs: dict[str, Any] = {
        "model": s.llm_model.strip() or "gpt-4o-mini",
        "api_key": s.resolve_llm_api_key(),
        "temperature": s.llm_temperature,
    }
    base = s.openai_base_url_optional()
    if base:
        kwargs["base_url"] = base
    return ChatOpenAI(**kwargs)


def node_analysis(state: TriageState) -> dict[str, Any]:
    if state.get("error"):
        return {}
    usage_cb = UsageMetadataCallbackHandler()
    llm = _chat_model().with_structured_output(TriageOutput)
    human = f"""INCIDENT (normalized):
{state.get("normalized_narrative", "")}

RETRIEVAL CONTEXT (snippets from runbooks, incidents, logs):
{state.get("rag_context", "")}

Produce triage JSON matching the schema."""
    try:
        out = llm.invoke(
            [
                SystemMessage(content=TRIAGE_SYSTEM),
                HumanMessage(content=human),
            ],
            config={"callbacks": [usage_cb]},
        )
        usage = aggregate_llm_usage(usage_cb)
        if isinstance(out, TriageOutput):
            return {"draft": out.model_dump(mode="json"), "llm_usage": usage}
        if isinstance(out, dict):
            return {"draft": out, "llm_usage": usage}
        return {
            "error": f"Unexpected LLM output type: {type(out)!r}",
            "llm_usage": usage,
        }
    except Exception as e:
        return {
            "error": f"LLM analysis failed: {e}",
            "llm_usage": aggregate_llm_usage(usage_cb),
        }


def node_enrich_triage(state: TriageState) -> dict[str, Any]:
    """Merge programmatic evidence, contradiction heuristics, and timeline after LLM draft."""
    if state.get("error"):
        return {}
    draft = state.get("draft")
    if not draft or not isinstance(draft, dict):
        return {}
    incident = state.get("incident") or {}
    if not isinstance(incident, dict):
        incident = {}

    hit_dicts = state.get("retrieval_hits") or []
    prog_evidence = evidence_from_retrieval_dicts(
        hit_dicts if isinstance(hit_dicts, list) else []
    )
    llm_evidence = draft.get("evidence") if isinstance(draft.get("evidence"), list) else []
    merged_evidence = merge_evidence_lists(prog_evidence, llm_evidence)

    conflict = detect_conflicting_signals(incident)
    existing_conflict = (draft.get("conflicting_signals_summary") or "").strip()
    if conflict and not existing_conflict:
        new_conflict = conflict
    else:
        new_conflict = draft.get("conflicting_signals_summary")

    prog_tl = build_programmatic_timeline(incident)
    llm_tl = draft.get("timeline") if isinstance(draft.get("timeline"), list) else []
    merged_tl = merge_timelines(prog_tl, [str(x) for x in llm_tl])

    svc = (
        str(incident.get("service_name") or incident.get("serviceName") or "").strip() or None
    )
    if not svc and draft.get("service_name"):
        svc = str(draft.get("service_name")).strip() or None

    enriched = {
        **draft,
        "evidence": merged_evidence,
        "conflicting_signals_summary": new_conflict,
        "timeline": merged_tl,
        "service_name": svc,
    }
    return {"draft": enriched}


def node_decision(state: TriageState) -> dict[str, Any]:
    if state.get("error"):
        return {}
    draft = state.get("draft")
    if not draft:
        return {"error": "No draft triage from analysis step"}
    incident = state.get("incident") if isinstance(state.get("incident"), dict) else {}
    draft = apply_operational_policy(incident, draft if isinstance(draft, dict) else {})
    sev = str(draft.get("severity", "")).upper()
    if sev == "CRITICAL":
        draft = {**draft, "escalate": True}
    return {"draft": draft}


def _empty_triage_extras() -> dict[str, Any]:
    return {
        "service_name": None,
        "evidence": [],
        "conflicting_signals_summary": None,
        "timeline": [],
    }


def node_output_formatter(state: TriageState) -> dict[str, Any]:
    if err := state.get("error"):
        return {
            "result": {
                "error": err,
                "incident_summary": "",
                "severity": "LOW",
                "likely_root_cause": "",
                "recommended_actions": ["Fix the reported error and retry triage."],
                "escalate": False,
                "confidence": 0.0,
                **_empty_triage_extras(),
            }
        }
    draft = state.get("draft") or {}
    try:
        validated = TriageOutput.model_validate(draft)
        return {"result": validated.model_dump(mode="json")}
    except ValidationError as e:
        return {
            "error": f"Output validation failed: {e}",
            "result": {
                "incident_summary": str(draft.get("incident_summary", "")),
                "severity": "LOW",
                "likely_root_cause": str(draft.get("likely_root_cause", "")),
                "recommended_actions": ["Validate agent output schema"],
                "escalate": bool(draft.get("escalate", False)),
                "confidence": 0.0,
                **_empty_triage_extras(),
            },
        }
