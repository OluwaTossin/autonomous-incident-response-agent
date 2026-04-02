"""Compile the triage LangGraph (five nodes)."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agent.nodes import (
    TriageState,
    node_analysis,
    node_decision,
    node_normalize_input,
    node_output_formatter,
    node_retrieval,
)


def build_triage_graph() -> StateGraph:
    g = StateGraph(TriageState)
    g.add_node("normalize_input", node_normalize_input)
    g.add_node("retrieval", node_retrieval)
    g.add_node("analysis", node_analysis)
    g.add_node("decision", node_decision)
    g.add_node("output_formatter", node_output_formatter)

    g.add_edge(START, "normalize_input")
    g.add_edge("normalize_input", "retrieval")
    g.add_edge("retrieval", "analysis")
    g.add_edge("analysis", "decision")
    g.add_edge("decision", "output_formatter")
    g.add_edge("output_formatter", END)
    return g


def run_triage(incident: dict[str, Any]) -> dict[str, Any]:
    """Run the graph; return the structured `result` dict (or error-shaped payload)."""
    graph = build_triage_graph().compile()
    final: TriageState = graph.invoke({"incident": incident})
    return final.get("result") or {}
