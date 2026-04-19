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


def test_corpus_data_root_falls_back_to_repo_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty workspace ``data/`` → use legacy ``data/``."""
    monkeypatch.delenv("RAG_CORPUS_ROOT", raising=False)
    reset_settings()
    try:
        assert corpus_data_root() == project_root() / "data"
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
