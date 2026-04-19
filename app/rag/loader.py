"""Load markdown and log files from the repo corpus."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.rag.config import CORPUS_PROJECT_PATTERNS, CORPUS_RELATIVE_PATTERNS, corpus_data_root, project_root


@dataclass
class SourceDocument:
    """One file worth of text."""

    text: str
    source: str
    doc_type: str


def load_corpus(root: Path | None = None) -> list[SourceDocument]:
    """
    Load corpus files.

    ``root`` defaults to ``corpus_data_root()`` (workspace ``data/``, bundled ``sample_data/default_demo/`` in demo mode, or workspace-only in user mode).
    Decision docs are always merged from ``project_root()`` via ``CORPUS_PROJECT_PATTERNS``.
    """
    data_root = root or corpus_data_root()
    out: list[SourceDocument] = []
    seen: set[Path] = set()

    for doc_type, pattern in CORPUS_RELATIVE_PATTERNS:
        for path in sorted(data_root.glob(pattern)):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                text = resolved.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if not text.strip():
                continue
            rel = str(resolved.relative_to(data_root))
            out.append(SourceDocument(text=text, source=rel, doc_type=doc_type))

    proj = project_root()
    for doc_type, pattern in CORPUS_PROJECT_PATTERNS:
        for path in sorted(proj.glob(pattern)):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                text = resolved.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if not text.strip():
                continue
            rel = str(resolved.relative_to(proj))
            out.append(SourceDocument(text=text, source=rel, doc_type=doc_type))

    return out
