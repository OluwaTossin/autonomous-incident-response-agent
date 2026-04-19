"""Central ``get_settings()`` merge behaviour."""

from __future__ import annotations

import pytest
import yaml

from app.config import get_settings, reset_settings


def test_yaml_sets_rag_top_k_when_env_unset(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAG_TOP_K", raising=False)
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(yaml.dump({"RAG_TOP_K": 3}), encoding="utf-8")
    monkeypatch.setenv("CONFIG_YAML", str(cfg))
    reset_settings()
    try:
        assert get_settings().rag_top_k == 3
    finally:
        reset_settings()


def test_invalid_aira_data_mode_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIRA_DATA_MODE", "bogus")
    reset_settings()
    try:
        with pytest.raises(ValueError, match="AIRA_DATA_MODE"):
            get_settings()
    finally:
        reset_settings()


def test_env_overrides_yaml_for_same_key(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(yaml.dump({"RAG_TOP_K": 3}), encoding="utf-8")
    monkeypatch.setenv("CONFIG_YAML", str(cfg))
    monkeypatch.setenv("RAG_TOP_K", "9")
    reset_settings()
    try:
        assert get_settings().rag_top_k == 9
    finally:
        reset_settings()


def test_operator_overrides_between_yaml_and_env(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``operator_overrides.yaml`` overrides CONFIG_YAML; process env wins over the file."""
    ws_root = tmp_path / "ws"
    wid = "w1"
    cfg_dir = ws_root / wid / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "operator_overrides.yaml").write_text(yaml.dump({"RAG_TOP_K": 7}), encoding="utf-8")

    main_yaml = tmp_path / "cfg.yaml"
    main_yaml.write_text(yaml.dump({"RAG_TOP_K": 3}), encoding="utf-8")
    monkeypatch.setenv("CONFIG_YAML", str(main_yaml))
    monkeypatch.setenv("WORKSPACES_ROOT", str(ws_root.resolve()))
    monkeypatch.setenv("WORKSPACE_ID", wid)
    monkeypatch.delenv("RAG_TOP_K", raising=False)
    reset_settings()
    try:
        assert get_settings().rag_top_k == 7
        monkeypatch.setenv("RAG_TOP_K", "9")
        reset_settings()
        assert get_settings().rag_top_k == 9
    finally:
        reset_settings()
