"""Characterization coverage for the Version 2 triage contracts."""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.agent import cli, graph, nodes
from app.api.triage_execution import run_full_triage
from app.rag.retrieve import RetrievalHit
from app.ui import gradio_app


def test_incident_normalization_preserves_aliases_and_extra_fields() -> None:
    raw = {
        "alertTitle": "Checkout latency",
        "service": "checkout-api",
        "env": "production",
        "metrics": "p95=900ms",
        "logExcerpt": "upstream timeout",
        "detected_at": "2026-09-23T10:00:00Z",
        "provider_event_id": "evt-123",
    }

    normalized = nodes.node_normalize_input({"incident": raw})

    assert normalized["incident"] == {
        **raw,
        "alert_title": "Checkout latency",
        "service_name": "checkout-api",
        "environment": "production",
        "logs": "upstream timeout",
        "metric_summary": "p95=900ms",
        "time_of_occurrence": "2026-09-23T10:00:00Z",
    }
    assert normalized["retrieval_query"] == (
        "Checkout latency checkout-api production p95=900ms upstream timeout"
    )
    assert "**Service:** checkout-api" in normalized["normalized_narrative"]


def test_retrieval_state_preserves_hit_shape_and_source_metadata(monkeypatch) -> None:
    hit = RetrievalHit(
        score=0.875,
        text="Scale the checkout workers.",
        source="data/runbooks/checkout.md",
        doc_type="runbook",
        chunk_index=3,
    )
    monkeypatch.setattr(nodes, "retrieve", lambda query, *, top_k: [hit])
    monkeypatch.setattr(nodes, "get_settings", lambda: SimpleNamespace(rag_top_k=4))

    out = nodes.node_retrieval({"retrieval_query": "checkout latency"})

    assert out["retrieval_hits"] == [
        {
            "score": 0.875,
            "source": "data/runbooks/checkout.md",
            "doc_type": "runbook",
            "chunk_index": 3,
        }
    ]
    assert "score=0.875" in out["rag_context"]
    assert "type=runbook" in out["rag_context"]
    assert "source=data/runbooks/checkout.md" in out["rag_context"]


def test_graph_result_and_audit_metadata_contract(monkeypatch) -> None:
    result = {
        "incident_summary": "Checkout is slow",
        "service_name": "checkout-api",
        "severity": "HIGH",
        "likely_root_cause": "Worker saturation",
        "recommended_actions": ["Scale workers"],
        "escalate": True,
        "confidence": 0.85,
        "evidence": [
            {
                "type": "runbook",
                "source": "data/runbooks/checkout.md",
                "reason": "Retrieved runbook guidance",
            }
        ],
        "conflicting_signals_summary": None,
        "timeline": ["T+0 alert"],
    }
    hit = {
        "score": 0.875,
        "source": "data/runbooks/checkout.md",
        "doc_type": "runbook",
        "chunk_index": 3,
    }

    class _CompiledGraph:
        def invoke(self, state):
            assert state == {"incident": {"alert_title": "Checkout latency"}}
            return {
                "result": result,
                "rag_context": "retrieved context",
                "retrieval_hits": [hit],
                "llm_usage": {"tokens_total": 17},
            }

    class _Graph:
        def compile(self):
            return _CompiledGraph()

    monkeypatch.setattr(graph, "build_triage_graph", lambda: _Graph())

    actual_result, metadata = graph.run_triage_with_audit(
        {"alert_title": "Checkout latency"}
    )

    assert actual_result == result
    assert metadata == {
        "rag_context": "retrieved context",
        "retrieval_hits": [hit],
        "llm_usage": {"tokens_total": 17},
    }


def test_structured_triage_result_contract() -> None:
    draft = {
        "incident_summary": "Checkout is slow",
        "service_name": "checkout-api",
        "severity": "HIGH",
        "likely_root_cause": "Worker saturation",
        "recommended_actions": [" Scale workers "],
        "escalate": True,
        "confidence": 0.85,
        "evidence": [
            {
                "type": "runbook",
                "source": "data/runbooks/checkout.md",
                "reason": "Retrieved runbook guidance",
            }
        ],
        "conflicting_signals_summary": "  ",
        "timeline": [" T+0 alert "],
    }

    out = nodes.node_output_formatter({"draft": draft})

    assert out["result"] == {
        **draft,
        "recommended_actions": ["Scale workers"],
        "conflicting_signals_summary": None,
        "timeline": ["T+0 alert"],
    }


def test_gradio_and_rest_share_full_triage_entrypoint() -> None:
    assert gradio_app.run_full_triage is run_full_triage


def test_cli_triage_output_and_exit_code_contract(tmp_path, monkeypatch, capsys) -> None:
    incident_path = tmp_path / "incident.json"
    incident_path.write_text(
        json.dumps({"alert_title": "Checkout latency", "service_name": "checkout-api"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli,
        "run_triage",
        lambda incident: {
            "incident_summary": incident["alert_title"],
            "severity": "MEDIUM",
            "escalate": False,
        },
    )
    monkeypatch.setattr(cli, "uuid4", lambda: "00000000-0000-4000-8000-000000000123")

    exit_code = cli.main(["--file", str(incident_path)])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output == {
        "incident_summary": "Checkout latency",
        "severity": "MEDIUM",
        "escalate": False,
        "triage_id": "00000000-0000-4000-8000-000000000123",
    }


def test_cli_graph_error_returns_exit_code_two(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(read=lambda: "{}"))
    monkeypatch.setattr(cli, "run_triage", lambda incident: {"error": "LLM unavailable"})

    exit_code = cli.main(["--stdin"])

    assert exit_code == 2
    assert json.loads(capsys.readouterr().out)["error"] == "LLM unavailable"
