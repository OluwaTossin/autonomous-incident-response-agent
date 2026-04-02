"""n8n helper routes (mock Jira, workflow log)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api.main import app

client = TestClient(app)


def test_mock_jira_returns_key() -> None:
    r = client.post(
        "/n8n/mock-jira/issue",
        json={"summary": "CPU spike", "description": "details"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["key"].startswith("MOCK-")
    assert data["fields"]["summary"] == "CPU spike"


def test_mock_jira_nested_fields() -> None:
    r = client.post(
        "/n8n/mock-jira/issue",
        json={"fields": {"summary": "Nested", "description": "x"}},
    )
    assert r.status_code == 200
    assert r.json()["fields"]["summary"] == "Nested"


def test_workflow_log_writes_when_enabled(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    logf = tmp_path / "n8n.jsonl"
    monkeypatch.setenv("N8N_WORKFLOW_LOG_JSONL", str(logf))
    monkeypatch.delenv("N8N_WORKFLOW_LOG_DISABLE", raising=False)

    r = client.post("/n8n/workflow-log", json={"workflow": "test", "x": 1})
    assert r.status_code == 200
    assert r.json()["status"] == "logged"
    row = json.loads(logf.read_text(encoding="utf-8").strip())
    assert row["event"]["workflow"] == "test"


def test_triage_feedback_writes_when_enabled(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    logf = tmp_path / "feedback.jsonl"
    monkeypatch.setenv("N8N_TRIAGE_FEEDBACK_JSONL", str(logf))
    monkeypatch.delenv("N8N_TRIAGE_FEEDBACK_DISABLE", raising=False)

    r = client.post(
        "/n8n/triage-feedback",
        json={
            "triage_id": "550e8400-e29b-41d4-a716-446655440000",
            "diagnosis_correct": True,
            "actions_useful": False,
            "notes": "Root cause was DB, not CPU",
            "triage_snapshot": {"confidence": 0.7},
        },
    )
    assert r.status_code == 200
    assert r.json()["status"] == "logged"
    row = json.loads(logf.read_text(encoding="utf-8").strip())
    assert row["triage_id"] == "550e8400-e29b-41d4-a716-446655440000"
    assert row["feedback"]["diagnosis_correct"] is True
    assert row["feedback"]["actions_useful"] is False


def test_triage_feedback_null_id_when_omitted(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    logf = tmp_path / "fb.jsonl"
    monkeypatch.setenv("N8N_TRIAGE_FEEDBACK_JSONL", str(logf))
    monkeypatch.delenv("N8N_TRIAGE_FEEDBACK_DISABLE", raising=False)
    r = client.post("/n8n/triage-feedback", json={"notes": "orphan"})
    assert r.status_code == 200
    row = json.loads(logf.read_text(encoding="utf-8").strip())
    assert row["triage_id"] is None
