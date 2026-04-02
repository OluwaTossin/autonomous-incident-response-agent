"""Load markdown and log files from the repo corpus."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.rag.config import CORPUS_GLOBS, project_root


@dataclass
class SourceDocument:
    """One file worth of text."""

    text: str
    source: str
    doc_type: str


def load_corpus(root: Path | None = None) -> list[SourceDocument]:
    root = root or project_root()
    out: list[SourceDocument] = []
    seen: set[Path] = set()

    for doc_type, pattern in CORPUS_GLOBS:
        for path in sorted(root.glob(pattern)):
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
            rel = str(resolved.relative_to(root))
            out.append(SourceDocument(text=text, source=rel, doc_type=doc_type))

    return out
