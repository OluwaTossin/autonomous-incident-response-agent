"""Phase 13 stdout JSON metrics (CloudWatch metric filters)."""

from __future__ import annotations

import json

import pytest

from app.api.metrics_log import triage_metrics_log_disabled, write_triage_metrics_line


def test_write_triage_metrics_line_writes_json(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRIAGE_METRICS_LOG_DISABLE", raising=False)
    write_triage_metrics_line({"event": "triage_metrics", "success": True, "duration_ms": 42})
    captured = capsys.readouterr()
    row = json.loads(captured.out.strip())
    assert row["event"] == "triage_metrics"
    assert row["duration_ms"] == 42


def test_write_respects_disable(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("TRIAGE_METRICS_LOG_DISABLE", "1")
    assert triage_metrics_log_disabled() is True
    write_triage_metrics_line({"event": "triage_metrics"})
    assert capsys.readouterr().out == ""
