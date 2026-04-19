"""Workspace path helpers and corpus root resolution."""

from __future__ import annotations

import shutil

import pytest

from app.config import reset_settings
from app.rag.config import corpus_data_root, project_root
from app.workspace.paths import workspace_data_dir, workspace_index_dir, workspace_root


def test_workspace_paths_use_default_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WORKSPACE_ID", raising=False)
    monkeypatch.delenv("WORKSPACES_ROOT", raising=False)
    reset_settings()
    try:
        root = project_root()
        assert workspace_root() == root / "workspaces" / "default"
        assert workspace_data_dir() == root / "workspaces" / "default" / "data"
        assert workspace_index_dir() == root / "workspaces" / "default" / "index"
    finally:
        reset_settings()


def test_corpus_data_root_demo_fallback_uses_bundled_sample(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty workspace + ``AIRA_DATA_MODE=demo`` → ``sample_data/default_demo/``."""
    monkeypatch.delenv("RAG_CORPUS_ROOT", raising=False)
    monkeypatch.delenv("AIRA_DATA_MODE", raising=False)
    reset_settings()
    try:
        from app.rag.config import bundled_demo_corpus_root

        assert corpus_data_root() == bundled_demo_corpus_root()
    finally:
        reset_settings()


def test_corpus_data_root_user_mode_stays_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """``AIRA_DATA_MODE=user`` with empty workspace → workspace ``data/`` only (no bundled sample)."""
    monkeypatch.delenv("RAG_CORPUS_ROOT", raising=False)
    monkeypatch.setenv("WORKSPACES_ROOT", str(tmp_path / "wsroot"))
    monkeypatch.setenv("AIRA_DATA_MODE", "user")
    reset_settings()
    try:
        assert corpus_data_root() == tmp_path / "wsroot" / "default" / "data"
    finally:
        reset_settings()


def test_corpus_data_root_prefers_workspace_when_populated(monkeypatch: pytest.MonkeyPatch) -> None:
    root = project_root()
    monkeypatch.setenv("WORKSPACES_ROOT", ".pytest_workspace_tmp")
    monkeypatch.delenv("RAG_CORPUS_ROOT", raising=False)
    wd = root / ".pytest_workspace_tmp" / "default" / "data" / "runbooks"
    wd.mkdir(parents=True, exist_ok=True)
    (wd / "x.md").write_text("# t", encoding="utf-8")
    reset_settings()
    try:
        assert corpus_data_root() == root / ".pytest_workspace_tmp" / "default" / "data"
    finally:
        reset_settings()
        shutil.rmtree(root / ".pytest_workspace_tmp", ignore_errors=True)
