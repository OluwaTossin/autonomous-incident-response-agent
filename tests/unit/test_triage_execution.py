"""Shared triage execution (API + Gradio)."""

from __future__ import annotations

import json
from unittest.mock import patch

from app.api.triage_execution import run_full_triage


def test_run_full_triage_adds_id_and_calls_graph(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRIAGE_AUDIT_JSONL", str(tmp_path / "a.jsonl"))
    monkeypatch.delenv("TRIAGE_AUDIT_DISABLE", raising=False)
    fake = {"incident_summary": "x", "severity": "LOW"}
    audit = {"rag_context": "", "retrieval_hits": []}
    with patch("app.api.triage_execution.run_triage_with_audit", return_value=(fake, audit)):
        out = run_full_triage({"alert_title": "t", "service_name": "s"})
    assert out["triage_id"]
    assert len(out["triage_id"]) == 36
    assert out["incident_summary"] == "x"
    line = (tmp_path / "a.jsonl").read_text(encoding="utf-8").strip()
    assert "triage_id" in line
    assert "alert_title" in line


def test_run_full_triage_preserves_audit_metadata_and_metrics(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("TRIAGE_AUDIT_JSONL", str(tmp_path / "a.jsonl"))
    monkeypatch.delenv("TRIAGE_AUDIT_DISABLE", raising=False)
    monkeypatch.setenv("TRIAGE_METRICS_LOG_DISABLE", "0")
    monkeypatch.setenv("AIRA_ENV", "characterization")
    result = {
        "incident_summary": "x",
        "severity": "high",
        "escalate": True,
        "error": "",
    }
    metadata = {
        "rag_context": "context sent to the model",
        "retrieval_hits": [
            {
                "score": 0.75,
                "source": "runbook.md",
                "doc_type": "runbook",
                "chunk_index": 2,
            }
        ],
        "llm_usage": {
            "tokens_prompt": 10,
            "tokens_completion": 5,
            "tokens_total": 15,
        },
    }

    with patch(
        "app.api.triage_execution.run_triage_with_audit",
        return_value=(result, metadata),
    ):
        out = run_full_triage({"alert_title": "t", "service_name": "s"})

    audit_row = json.loads((tmp_path / "a.jsonl").read_text(encoding="utf-8"))
    metrics_row = json.loads(capsys.readouterr().out)
    assert audit_row["triage_id"] == out["triage_id"]
    assert audit_row["retrieved_context"] == "context sent to the model"
    assert audit_row["top_k_sources"] == [
        {
            "source": "runbook.md",
            "doc_type": "runbook",
            "score": 0.75,
            "chunk_index": 2,
        }
    ]
    assert metrics_row["triage_id"] == out["triage_id"]
    assert metrics_row["stack_environment"] == "characterization"
    assert metrics_row["outcome"] == "success"
    assert metrics_row["severity_metric"] == "HIGH"
    assert metrics_row["escalate_str"] == "true"
    assert metrics_row["tokens_total"] == 15
