"""Admin ingestion API (V2.7) — no live LLM for reindex tests (mocked)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import reset_settings

# Import app after env is stable for module-level client; tests patch env + reset_settings per case.
from app.api.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _admin_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Dedicated workspace + admin key for admin tests."""
    monkeypatch.setenv("WORKSPACES_ROOT", str(tmp_path / "ws"))
    monkeypatch.setenv("WORKSPACE_ID", "admintest")
    monkeypatch.setenv("ADMIN_API_KEY", "admin-secret-test")
    monkeypatch.setenv("API_KEY", "triage-key-test")
    monkeypatch.setenv("AIRA_DATA_MODE", "user")
    monkeypatch.setenv("RAG_WORKSPACE_ONLY", "1")
    monkeypatch.setenv("API_RATE_LIMIT_DISABLED", "1")
    reset_settings()
    yield
    reset_settings()


def test_admin_disabled_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    reset_settings()
    try:
        r = client.get("/admin/files")
        assert r.status_code == 503
        assert r.json()["detail"]["error"] == "admin_disabled"
    finally:
        reset_settings()


def test_admin_files_requires_header() -> None:
    r = client.get("/admin/files")
    assert r.status_code == 401


def test_admin_files_forbidden_with_triage_key() -> None:
    r = client.get("/admin/files", headers={"x-admin-api-key": "triage-key-test"})
    assert r.status_code == 403


def test_admin_files_ok_empty() -> None:
    r = client.get("/admin/files", headers={"x-admin-api-key": "admin-secret-test"})
    assert r.status_code == 200
    assert r.json() == {"files": []}


def test_admin_upload_rejects_bad_name() -> None:
    r = client.post(
        "/admin/upload",
        headers={"x-admin-api-key": "admin-secret-test"},
        data={"category": "runbooks"},
        files={"file": ("../evil.md", b"# x", "text/markdown")},
    )
    assert r.status_code == 400


def test_admin_upload_writes_file() -> None:
    r = client.post(
        "/admin/upload",
        headers={"x-admin-api-key": "admin-secret-test"},
        data={"category": "runbooks"},
        files={"file": ("note.md", b"# hello", "text/markdown")},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["path"] == "runbooks/note.md"
    r2 = client.get("/admin/files", headers={"x-admin-api-key": "admin-secret-test"})
    paths = {f["path"] for f in r2.json()["files"]}
    assert "runbooks/note.md" in paths


def test_admin_reindex_and_index_status_mocked() -> None:
    with patch("app.api.admin_routes.cmd_build_index", return_value=0):
        r = client.post("/admin/reindex", headers={"x-admin-api-key": "admin-secret-test"})
    assert r.status_code == 200
    assert r.json()["status"] == "completed"
    r2 = client.get("/admin/index-status", headers={"x-admin-api-key": "admin-secret-test"})
    assert r2.status_code == 200
    body = r2.json()
    assert body["phase"] == "success"
    assert body["exit_code"] == 0
