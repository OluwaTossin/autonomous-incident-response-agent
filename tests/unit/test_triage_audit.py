"""Triage JSONL audit helper."""

from __future__ import annotations

import json

import pytest

from app.api.audit import append_triage_jsonl, triage_audit_path


def test_append_triage_jsonl_writes_line(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "audit.jsonl"
    monkeypatch.setenv("TRIAGE_AUDIT_JSONL", str(target))
    monkeypatch.delenv("TRIAGE_AUDIT_DISABLE", raising=False)

    append_triage_jsonl(
        {"alert_title": "x"},
        {"severity": "LOW", "incident_summary": "y"},
    )
    assert target.is_file()
    row = json.loads(target.read_text(encoding="utf-8").strip())
    assert row["input"]["alert_title"] == "x"
    assert row["output"]["severity"] == "LOW"
    assert "timestamp" in row


def test_triage_audit_respects_disable(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    target = tmp_path / "empty.jsonl"
    monkeypatch.setenv("TRIAGE_AUDIT_JSONL", str(target))
    monkeypatch.setenv("TRIAGE_AUDIT_DISABLE", "1")

    append_triage_jsonl({}, {})
    assert not target.exists()


def test_default_path_under_data_logs() -> None:
    p = triage_audit_path()
    assert p.name == "triage_outputs.jsonl"
    assert "logs" in p.parts
