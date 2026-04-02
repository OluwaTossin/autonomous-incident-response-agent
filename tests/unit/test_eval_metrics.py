"""Evaluation metrics (no LLM)."""

from __future__ import annotations

from app.eval.metrics import evaluate_case, evidence_grounding_ratio
from app.eval.schema import GoldExpect


def test_evaluate_severity_any_of_pass() -> None:
    r = evaluate_case(
        "x",
        {"severity": "HIGH", "escalate": True, "recommended_actions": ["a", "b"], "incident_summary": "ok"},
        {"retrieval_hits": []},
        GoldExpect(severity_any_of=["HIGH", "CRITICAL"]),
        latency_ms=12.0,
    )
    assert r["passed"]
    assert r["checks"]["severity_ok"] is True


def test_evaluate_severity_fail() -> None:
    r = evaluate_case(
        "x",
        {"severity": "LOW", "recommended_actions": ["a"]},
        {"retrieval_hits": []},
        GoldExpect(severity_any_of=["HIGH", "CRITICAL"]),
        latency_ms=1.0,
    )
    assert not r["passed"]


def test_evidence_grounding() -> None:
    result = {
        "severity": "HIGH",
        "recommended_actions": ["x"],
        "incident_summary": "s",
        "likely_root_cause": "r",
        "evidence": [
            {"type": "log", "source": "data/logs/a.log", "reason": "r1"},
            {"type": "log", "source": "unknown/path", "reason": "r2"},
        ],
    }
    hits = [{"source": "data/logs/a.log", "score": 0.5}]
    ratio, g, t = evidence_grounding_ratio(result, hits)
    assert t == 2
    assert g == 1
    assert ratio == 0.5


def test_graph_error_fails() -> None:
    r = evaluate_case(
        "e",
        {"error": "LLM unavailable"},
        {"retrieval_hits": []},
        GoldExpect(),
        latency_ms=0.0,
    )
    assert not r["passed"]
    assert "graph_error" in r["failures"][0]
