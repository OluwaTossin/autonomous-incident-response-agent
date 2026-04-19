"""Validate workspace layout and corpus file conventions (Version 2)."""

from __future__ import annotations

import re
from pathlib import Path

from app.config import get_settings
from app.rag.config import workspace_corpus_has_files
from app.workspace.paths import workspace_data_dir, workspace_index_dir, workspace_root

_WORKSPACE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

# Under ``data/`` — optional; missing dirs are warnings, not errors.
_EXPECTED_SUBDIRS = ("runbooks", "incidents", "logs", "knowledge_base")

# Warn on other suffixes (operators may add PDFs later — not indexed today).
_ALLOWED_SUFFIXES = frozenset(
    {
        ".md",
        ".markdown",
        ".txt",
        ".log",
        ".yaml",
        ".yml",
        "",
    }
)

_SKIP_FILES = frozenset({".DS_Store", ".gitkeep", "Thumbs.db"})


def validate_workspace_id(workspace_id: str) -> str | None:
    w = workspace_id.strip()
    if not w:
        return "Workspace id must be non-empty."
    if not _WORKSPACE_ID_RE.match(w):
        return (
            "Workspace id must match ^[a-zA-Z0-9_-]{1,64}$ "
            "(use letters, digits, hyphen, underscore only)."
        )
    return None


def _unexpected_suffix_files(data_dir: Path, *, cap: int = 200) -> list[str]:
    out: list[str] = []
    if not data_dir.is_dir():
        return out
    for path in data_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.name in _SKIP_FILES:
            continue
        suf = path.suffix.lower()
        if suf not in _ALLOWED_SUFFIXES:
            try:
                rel = path.relative_to(data_dir)
            except ValueError:
                rel = path
            out.append(f"{rel} (suffix {suf!r})")
            if len(out) >= cap:
                break
    return out


def validate_workspace_layout(
    *,
    require_corpus_files: bool = False,
) -> tuple[list[str], list[str]]:
    """
    Return ``(errors, warnings)`` for the active ``WORKSPACE_ID`` in settings.

    ``require_corpus_files``: if True, error when workspace ``data/`` has no
    runbook/incident/log/knowledge files (strict product mode).
    """
    errors: list[str] = []
    warnings: list[str] = []

    wid = get_settings().workspace_id.strip() or "default"
    err = validate_workspace_id(wid)
    if err:
        errors.append(err)
        return errors, warnings

    root = workspace_root()
    data_dir = workspace_data_dir()
    index_dir = workspace_index_dir()

    if not root.exists():
        warnings.append(f"Workspace root does not exist yet (will be created on index write): {root}")

    if not data_dir.exists():
        warnings.append(
            f"Workspace data directory missing: {data_dir}\n"
            f"  Create it and add subfolders, e.g.: mkdir -p {data_dir}/{{runbooks,incidents,logs,knowledge_base}}"
        )
    else:
        for name in _EXPECTED_SUBDIRS:
            sub = data_dir / name
            if not sub.is_dir():
                warnings.append(f"Optional corpus subdir missing: {sub.name}/ (create if you use that corpus type)")

    if not workspace_corpus_has_files(data_dir):
        msg = (
            f"No corpus files found under {data_dir} (expected *.md / *.log under runbooks, incidents, logs, knowledge_base). "
            "Index build may still include repo `docs/decisions/` only."
        )
        if require_corpus_files:
            errors.append(msg)
        else:
            warnings.append(msg)

    unexpected = _unexpected_suffix_files(data_dir, cap=200)
    for rel in unexpected[:50]:
        warnings.append(f"Unsupported file type for current indexer (skipped at build if unreadable): {rel}")
    if len(unexpected) >= 200:
        warnings.append("Unexpected-suffix scan stopped at 200 paths (see docs/bring-your-own-data.md).")
    elif len(unexpected) > 50:
        warnings.append(f"... and {len(unexpected) - 50} more unexpected-suffix paths (first 50 shown).")

    if index_dir.exists() and any(index_dir.iterdir()):
        warnings.append(f"Index directory already has files: {index_dir} (will be overwritten by save_index).")

    return errors, warnings
