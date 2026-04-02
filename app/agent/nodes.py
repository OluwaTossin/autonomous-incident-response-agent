"""LangGraph nodes: normalize → retrieve → analyze → decision → format."""

from __future__ import annotations

import os
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from app.agent.prompts import TRIAGE_SYSTEM
from app.models.incident import IncidentPayload
from app.models.triage import TriageOutput
from app.rag.config import openai_api_key, openai_base_url
from app.rag.retrieve import retrieve


class TriageState(TypedDict, total=False):
    incident: dict[str, Any]
    normalized_narrative: str
    retrieval_query: str
    rag_context: str
    draft: dict[str, Any]
    result: dict[str, Any]
    error: str


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


def node_retrieval(state: TriageState) -> dict[str, Any]:
    if state.get("error"):
        return {}
    q = state.get("retrieval_query") or ""
    try:
        hits = retrieve(q, top_k=int(os.environ.get("RAG_TOP_K", "8")))
    except Exception as e:
        return {
            "rag_context": (
                f"(Vector retrieval failed — build index with "
                f"`uv run python -m app.rag.cli build-index`. Error: {e})"
            )
        }
    if not hits:
        return {"rag_context": "(No retrieval hits; index may be empty or query mismatched.)"}
    blocks = []
    for i, h in enumerate(hits, 1):
        blocks.append(
            f"[{i}] score={h.score:.3f} type={h.doc_type} source={h.source}\n{h.text}"
        )
    return {"rag_context": "\n\n---\n\n".join(blocks)}


def _chat_model() -> ChatOpenAI:
    model = os.environ.get("LLM_MODEL", "gpt-4o-mini").strip()
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": openai_api_key(),
        "temperature": float(os.environ.get("LLM_TEMPERATURE", "0.2")),
    }
    base = openai_base_url()
    if base:
        kwargs["base_url"] = base
    return ChatOpenAI(**kwargs)


def node_analysis(state: TriageState) -> dict[str, Any]:
    if state.get("error"):
        return {}
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
            ]
        )
        if isinstance(out, TriageOutput):
            return {"draft": out.model_dump(mode="json")}
        if isinstance(out, dict):
            return {"draft": out}
        return {"error": f"Unexpected LLM output type: {type(out)!r}"}
    except Exception as e:
        return {"error": f"LLM analysis failed: {e}"}


def node_decision(state: TriageState) -> dict[str, Any]:
    if state.get("error"):
        return {}
    draft = state.get("draft")
    if not draft:
        return {"error": "No draft triage from analysis step"}
    sev = str(draft.get("severity", "")).upper()
    if sev == "CRITICAL":
        draft = {**draft, "escalate": True}
    return {"draft": draft}


def _empty_triage_extras() -> dict[str, Any]:
    return {
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
