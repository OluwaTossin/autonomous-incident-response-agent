"""Product workspace validation and build entrypoints."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import reset_settings
from app.product.cli import main_build_index, main_validate_workspace
from app.product.workspace_layout import validate_workspace_id, validate_workspace_layout
from app.rag.config import bundled_demo_corpus_root, corpus_data_root, workspace_corpus_has_files


def test_validate_workspace_id_rejects_space() -> None:
    assert validate_workspace_id("a b") is not None
    assert validate_workspace_id("acme-1") is None


def test_validate_layout_strict_errors_when_no_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "wsroot"
    root.mkdir()
    monkeypatch.setenv("WORKSPACES_ROOT", str(root))
    monkeypatch.setenv("WORKSPACE_ID", "tenant1")
    reset_settings()
    try:
        errs, _ = validate_workspace_layout(require_corpus_files=True)
        assert errs
    finally:
        reset_settings()


def test_validate_layout_warns_on_pdf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "wsroot"
    data = root / "t1" / "data" / "runbooks"
    data.mkdir(parents=True)
    (data / "ok.md").write_text("# x", encoding="utf-8")
    (data / "x.pdf").write_bytes(b"%PDF-1.4")
    monkeypatch.setenv("WORKSPACES_ROOT", str(root))
    monkeypatch.setenv("WORKSPACE_ID", "t1")
    reset_settings()
    try:
        errs, warns = validate_workspace_layout()
        assert not errs
        assert any(".pdf" in w for w in warns)
    finally:
        reset_settings()


def test_workspace_corpus_has_files_public_alias(tmp_path: Path) -> None:
    d = tmp_path / "d"
    rb = d / "runbooks"
    rb.mkdir(parents=True)
    (rb / "a.md").write_text("x", encoding="utf-8")
    assert workspace_corpus_has_files(d) is True
    assert workspace_corpus_has_files(tmp_path / "empty") is False


def test_corpus_data_root_workspace_only_creates_workspace_and_reads_demo_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Workspace ``data/`` is created; empty corpus + demo mode reads ``sample_data/default_demo/``."""
    root = tmp_path / "wsroot"
    monkeypatch.setenv("WORKSPACES_ROOT", str(root))
    monkeypatch.setenv("WORKSPACE_ID", "newtenant")
    monkeypatch.setenv("RAG_CORPUS_ROOT", "")
    monkeypatch.setenv("RAG_WORKSPACE_ONLY", "1")
    monkeypatch.delenv("AIRA_DATA_MODE", raising=False)
    reset_settings()
    try:
        cr = corpus_data_root()
        assert (root / "newtenant" / "data").is_dir()
        assert cr == bundled_demo_corpus_root()
    finally:
        reset_settings()


def test_main_validate_workspace_cli_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "wsroot"
    data = root / "acme" / "data" / "runbooks"
    data.mkdir(parents=True)
    (data / "r.md").write_text("# r", encoding="utf-8")
    monkeypatch.setenv("WORKSPACES_ROOT", str(root))
    reset_settings()
    try:
        assert main_validate_workspace(["--workspace", "acme"]) == 0
    finally:
        reset_settings()


def test_main_build_index_dry_run_no_rag_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "wsroot"
    data = root / "acme" / "data" / "runbooks"
    data.mkdir(parents=True)
    (data / "r.md").write_text("# r", encoding="utf-8")
    monkeypatch.setenv("WORKSPACES_ROOT", str(root))

    called: list[list[str]] = []

    def fake_rag(argv: list[str]) -> int:
        called.append(argv)
        return 0

    monkeypatch.setattr("app.product.cli.rag_main", fake_rag)
    reset_settings()
    try:
        assert main_build_index(["--workspace", "acme", "--dry-run"]) == 0
        assert called == []
    finally:
        reset_settings()


def test_main_build_index_strict_fails_without_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "wsroot"
    (root / "solo" / "data").mkdir(parents=True)
    monkeypatch.setenv("WORKSPACES_ROOT", str(root))

    def _rag_should_not_run(_: list[str]) -> int:
        raise AssertionError("rag should not run")

    monkeypatch.setattr("app.product.cli.rag_main", _rag_should_not_run)
    reset_settings()
    try:
        assert main_build_index(["--workspace", "solo", "--strict"]) == 1
    finally:
        reset_settings()
