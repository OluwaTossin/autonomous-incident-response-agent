"""GET /operator-config and PATCH /admin/operator-settings (V2.8)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.api.main import app
from app.config import reset_settings
from app.workspace.paths import workspace_config_dir

client = TestClient(app)


@pytest.fixture
def _op_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ws_root = tmp_path / "ws"
    monkeypatch.setenv("WORKSPACES_ROOT", str(ws_root.resolve()))
    monkeypatch.setenv("WORKSPACE_ID", "opcfg")
    monkeypatch.setenv("API_KEY", "triage-op")
    monkeypatch.setenv("ADMIN_API_KEY", "admin-op")
    monkeypatch.setenv("API_RATE_LIMIT_DISABLED", "1")
    reset_settings()
    yield
    reset_settings()


def test_operator_config_401_when_triage_key_required(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ws_root = tmp_path / "ws2"
    monkeypatch.setenv("WORKSPACES_ROOT", str(ws_root.resolve()))
    monkeypatch.setenv("WORKSPACE_ID", "x")
    monkeypatch.setenv("API_KEY", "secret-triage")
    monkeypatch.setenv("API_RATE_LIMIT_DISABLED", "1")
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    reset_settings()
    try:
        r = client.get("/operator-config")
        assert r.status_code == 401
        r2 = client.get("/operator-config", headers={"x-api-key": "wrong"})
        assert r2.status_code == 401
        r3 = client.get("/operator-config", headers={"x-api-key": "secret-triage"})
        assert r3.status_code == 200
        assert r3.json()["workspace_id"] == "x"
    finally:
        reset_settings()


def test_operator_config_ok_with_triage_key(_op_env: None) -> None:
    r = client.get("/operator-config", headers={"x-api-key": "triage-op"})
    assert r.status_code == 200
    data = r.json()
    assert data["workspace_id"] == "opcfg"
    assert data["aira_data_mode"] == "demo"
    assert data["admin_routes_enabled"] is True
    assert data["triage_api_key_configured"] is True


def test_admin_operator_settings_writes_overrides(_op_env: None) -> None:
    r = client.patch(
        "/admin/operator-settings",
        headers={"x-admin-api-key": "admin-op"},
        json={"rag_top_k": 12, "aira_data_mode": "user"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "updated"
    assert set(body["updated_keys"]) == {"RAG_TOP_K", "AIRA_DATA_MODE"}

    ow = workspace_config_dir() / "operator_overrides.yaml"
    assert ow.is_file()
    loaded = yaml.safe_load(ow.read_text(encoding="utf-8"))
    assert int(loaded["RAG_TOP_K"]) == 12
    assert loaded["AIRA_DATA_MODE"] == "user"

    r2 = client.get("/operator-config", headers={"x-api-key": "triage-op"})
    assert r2.status_code == 200
    assert r2.json()["rag_top_k"] == 12
    assert r2.json()["aira_data_mode"] == "user"
