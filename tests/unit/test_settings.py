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
