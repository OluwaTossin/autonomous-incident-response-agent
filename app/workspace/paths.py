"""Filesystem paths for the active workspace (Version 2 layout)."""

from __future__ import annotations

from pathlib import Path

from app.config import get_settings


def project_root() -> Path:
    """Repository root (contains ``app/``, ``data/``, ``workspaces/``, …)."""
    return Path(__file__).resolve().parents[2]


def workspace_root() -> Path:
    """``<repo>/workspaces/<WORKSPACE_ID>/``"""
    s = get_settings()
    wid = (s.workspace_id or "default").strip() or "default"
    root_name = (s.workspaces_root or "workspaces").strip() or "workspaces"
    return project_root() / root_name / wid


def workspace_data_dir() -> Path:
    """Corpus lives under ``…/data/{runbooks,logs,incidents,knowledge_base}/``."""
    return workspace_root() / "data"


def workspace_index_dir() -> Path:
    """FAISS bundle (``index.faiss``, ``chunks.jsonl``, ``meta.json``)."""
    return workspace_root() / "index"


def workspace_config_dir() -> Path:
    """Optional workspace-scoped overrides (future)."""
    return workspace_root() / "config"
