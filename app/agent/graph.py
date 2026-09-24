"""Compile the triage LangGraph (normalize → retrieve → analyze → enrich → decision → format)."""

from __future__ import annotations

from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agent.nodes import (
    TriageState,
    node_analysis,
    node_decision,
    node_enrich_triage,
    node_normalize_input,
    node_output_formatter,
    node_retrieval,
)
from app.knowledge.contracts import RetrievalContext


def build_triage_graph(
    retrieval_context: RetrievalContext | None = None,
) -> StateGraph:
    g = StateGraph(TriageState)
    g.add_node("normalize_input", node_normalize_input)
    retrieval_node = (
        node_retrieval
        if retrieval_context is None
        else partial(node_retrieval, retrieval_context=retrieval_context)
    )
    g.add_node("retrieval", retrieval_node)
    g.add_node("analysis", node_analysis)
    g.add_node("enrich_triage", node_enrich_triage)
    g.add_node("decision", node_decision)
    g.add_node("output_formatter", node_output_formatter)

    g.add_edge(START, "normalize_input")
    g.add_edge("normalize_input", "retrieval")
    g.add_edge("retrieval", "analysis")
    g.add_edge("analysis", "enrich_triage")
    g.add_edge("enrich_triage", "decision")
    g.add_edge("decision", "output_formatter")
    g.add_edge("output_formatter", END)
    return g


def run_triage_with_audit(
    incident: dict[str, Any],
    *,
    retrieval_context: RetrievalContext | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Run the graph; return (triage_result, audit_metadata).

    `audit_metadata` contains `rag_context` and `retrieval_hits` as seen after retrieval
    (same text the LLM receives), for logging and RAG evaluation — not returned to API clients.
    """
    graph_builder = (
        build_triage_graph()
        if retrieval_context is None
        else build_triage_graph(retrieval_context)
    )
    graph = graph_builder.compile()
    final: TriageState = graph.invoke({"incident": incident})
    result = final.get("result") or {}
    rag = final.get("rag_context")
    hits = final.get("retrieval_hits")
    raw_usage = final.get("llm_usage")
    llm_usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
    meta: dict[str, Any] = {
        "rag_context": rag if isinstance(rag, str) else "",
        "retrieval_hits": hits if isinstance(hits, list) else [],
        "llm_usage": llm_usage,
    }
    return result, meta


def run_triage(
    incident: dict[str, Any],
    *,
    retrieval_context: RetrievalContext | None = None,
) -> dict[str, Any]:
    """Run the graph; return the structured `result` dict (or error-shaped payload)."""
    out, _ = run_triage_with_audit(incident, retrieval_context=retrieval_context)
    return out
