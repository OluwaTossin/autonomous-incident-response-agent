"""Evaluation metrics (no LLM)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.eval.metrics import evaluate_case, evidence_grounding_ratio
from app.eval.schema import GoldCase, GoldExpect

ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / "data" / "eval" / "gold.jsonl"


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


def test_strict_keyword_and_retrieval_checks() -> None:
    hits = [{"source": "data/logs/app.log", "score": 0.2}]
    r = evaluate_case(
        "k",
        {
            "severity": "HIGH",
            "recommended_actions": ["a"],
            "incident_summary": "CPU spike on payment service",
            "likely_root_cause": "High CPU due to hot path",
        },
        {"retrieval_hits": hits},
        GoldExpect(
            summary_contains_all=["CPU", "payment"],
            root_cause_contains_any=["cpu", "memory"],
            retrieval_source_contains_any=["data/"],
            min_top_retrieval_score=0.05,
        ),
        latency_ms=1.0,
    )
    assert r["passed"]
    ch = r["checks"]
    assert ch["summary_keywords_ok"] is True
    assert ch["root_cause_hint_ok"] is True
    assert ch["retrieval_source_ok"] is True
    assert ch["min_top_score_ok"] is True


@pytest.mark.skipif(not GOLD.is_file(), reason="gold.jsonl not present")
def test_gold_jsonl_parses() -> None:
    n = 0
    with GOLD.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            GoldCase.model_validate_json(line)
            n += 1
    assert n >= 20
