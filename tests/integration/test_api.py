"""HTTP tests for FastAPI (no live LLM when triage is mocked)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.main import SERVICE_VERSION, app

client = TestClient(app)


def test_health() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_version() -> None:
    r = client.get("/version")
    assert r.status_code == 200
    data = r.json()
    assert data["version"] == SERVICE_VERSION
    assert "service" in data


def test_ingest_accepts_minimal_payload() -> None:
    r = client.post(
        "/ingest-incident",
        json={"alert_title": "CPU high", "service_name": "checkout"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "accepted"
    assert "received_at" in data
    assert data["normalized"]["alert_title"] == "CPU high"
    assert data["normalized"]["service_name"] == "checkout"


def test_ingest_rejects_non_object() -> None:
    r = client.post("/ingest-incident", json=["not", "an", "object"])
    assert r.status_code == 422


@pytest.fixture
def fake_triage() -> dict:
    return {
        "incident_summary": "Synthetic",
        "severity": "LOW",
        "likely_root_cause": "Test",
        "recommended_actions": ["Verify"],
        "escalate": False,
        "confidence": 0.5,
        "evidence": [],
        "conflicting_signals_summary": None,
        "timeline": [],
    }


def test_triage_calls_graph(fake_triage: dict) -> None:
    with patch("app.api.main.run_triage", return_value=fake_triage) as m:
        r = client.post(
            "/triage",
            json={"alert_title": "x", "service_name": "y"},
        )
    assert r.status_code == 200
    assert r.json() == fake_triage
    m.assert_called_once()


def test_triage_validation_error() -> None:
    r = client.post("/triage", json=["invalid"])
    assert r.status_code == 422
