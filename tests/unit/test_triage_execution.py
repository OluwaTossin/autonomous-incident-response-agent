"""Shared triage execution (API + Gradio)."""

from __future__ import annotations

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
