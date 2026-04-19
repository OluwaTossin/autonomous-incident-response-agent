"""V2.9 security baseline: triage vs admin auth, upload guards, concurrent reindex, rate limits."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.api.security import rate_limit_disabled
from app.config import reset_settings

client = TestClient(app)

_TRIAGE_JSON = {
    "alert_title": "CPU",
    "service_name": "api",
}

_FAKE_TRIAGE_OUT = {
    "triage_id": "11111111-1111-4111-8111-111111111111",
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


@pytest.fixture
def dual_keys(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WORKSPACES_ROOT", str(tmp_path / "ws"))
    monkeypatch.setenv("WORKSPACE_ID", "secv29")
    monkeypatch.setenv("ADMIN_API_KEY", "admin-only-key")
    monkeypatch.setenv("API_KEY", "triage-only-key")
    monkeypatch.setenv("AIRA_DATA_MODE", "user")
    monkeypatch.setenv("RAG_WORKSPACE_ONLY", "1")
    monkeypatch.setenv("API_RATE_LIMIT_DISABLED", "1")
    reset_settings()
    yield
    reset_settings()


def test_post_triage_401_wrong_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", "expected-triage-key")
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    reset_settings()
    try:
        r = client.post(
            "/triage",
            json=_TRIAGE_JSON,
            headers={"x-api-key": "wrong-key"},
        )
        assert r.status_code == 401
    finally:
        reset_settings()


def test_post_triage_401_when_api_key_configured_no_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", "secret-triage")
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    reset_settings()
    try:
        r = client.post("/triage", json=_TRIAGE_JSON)
        assert r.status_code == 401
    finally:
        reset_settings()


def test_post_ingest_401_when_api_key_configured_no_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", "secret-triage")
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    reset_settings()
    try:
        r = client.post("/ingest-incident", json=_TRIAGE_JSON)
        assert r.status_code == 401
    finally:
        reset_settings()


def test_operator_config_401_wrong_triage_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", "good-triage")
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    reset_settings()
    try:
        r = client.get("/operator-config", headers={"x-api-key": "wrong"})
        assert r.status_code == 401
    finally:
        reset_settings()


def test_admin_patch_forbidden_with_triage_key_as_admin_header(dual_keys: None) -> None:
    r = client.patch(
        "/admin/operator-settings",
        headers={"x-admin-api-key": "triage-only-key"},
        json={"rag_top_k": 5},
    )
    assert r.status_code == 403


def test_admin_upload_forbidden_with_triage_key_as_admin_header(dual_keys: None) -> None:
    r = client.post(
        "/admin/upload",
        headers={"x-admin-api-key": "triage-only-key"},
        data={"category": "runbooks"},
        files={"file": ("a.md", b"# x", "text/plain")},
    )
    assert r.status_code == 403


def test_admin_upload_415_unsupported_extension(dual_keys: None) -> None:
    r = client.post(
        "/admin/upload",
        headers={"x-admin-api-key": "admin-only-key"},
        data={"category": "runbooks"},
        files={"file": ("evil.exe", b"MZ", "application/octet-stream")},
    )
    assert r.status_code == 415


def test_admin_upload_413_payload_too_large(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WORKSPACES_ROOT", str(tmp_path / "ws"))
    monkeypatch.setenv("WORKSPACE_ID", "bigup")
    monkeypatch.setenv("ADMIN_API_KEY", "admin-x")
    monkeypatch.setenv("API_KEY", "triage-x")
    monkeypatch.setenv("ADMIN_UPLOAD_MAX_BYTES", "20")
    monkeypatch.setenv("API_RATE_LIMIT_DISABLED", "1")
    reset_settings()
    try:
        r = client.post(
            "/admin/upload",
            headers={"x-admin-api-key": "admin-x"},
            data={"category": "logs"},
            files={"file": ("big.log", b"x" * 80, "text/plain")},
        )
        assert r.status_code == 413
        detail = r.json()["detail"]
        assert detail["error"] == "payload_too_large"
    finally:
        reset_settings()


def test_post_triage_429_when_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    monkeypatch.setenv("API_RATE_LIMIT_DISABLED", "0")
    monkeypatch.setenv("API_RATE_LIMIT_TRIAGE", "1/second")
    reset_settings()
    app.state.limiter.enabled = True
    app.state.limiter.reset()
    try:
        with patch("app.api.main.run_full_triage", return_value=_FAKE_TRIAGE_OUT):
            r1 = client.post("/triage", json=_TRIAGE_JSON)
            assert r1.status_code == 200
            r2 = client.post("/triage", json=_TRIAGE_JSON)
            assert r2.status_code == 429
            body = r2.json()
            assert "error" in body or "detail" in body
    finally:
        reset_settings()
        app.state.limiter.reset()
        app.state.limiter.enabled = not rate_limit_disabled()
