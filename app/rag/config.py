"""Environment and path configuration for RAG."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

# Load project root `.env` only — not `.env.example` (that file is a template for Git).
_root = Path(__file__).resolve().parents[2]
load_dotenv(_root / ".env", override=False)


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def rag_index_dir() -> Path:
    """FAISS bundle directory. Uses ``RAG_INDEX_DIR`` when set; else ``workspaces/<id>/index``."""
    from app.config import get_settings
    from app.workspace.paths import workspace_index_dir

    rel = get_settings().rag_index_dir.strip()
    if rel:
        p = Path(rel)
        if not p.is_absolute():
            p = project_root() / p
        return p
    return workspace_index_dir()


def corpus_data_root() -> Path:
    """Primary corpus root: explicit ``RAG_CORPUS_ROOT``, workspace-only mode, else heuristics."""
    from app.config import get_settings
    from app.workspace.paths import workspace_data_dir

    s = get_settings()
    if s.rag_corpus_root.strip():
        p = Path(s.rag_corpus_root.strip())
        return p if p.is_absolute() else project_root() / p
    wd = workspace_data_dir()
    if s.rag_workspace_corpus_only:
        wd.mkdir(parents=True, exist_ok=True)
        return wd
    if _workspace_corpus_has_files(wd):
        return wd
    return project_root() / "data"


def _workspace_corpus_has_files(wd: Path) -> bool:
    if not wd.is_dir():
        return False
    for pattern in (
        "runbooks/**/*.md",
        "incidents/**/*.md",
        "incidents/*.md",
        "logs/*.log",
        "knowledge_base/**/*.md",
    ):
        if any(wd.glob(pattern)):
            return True
    return False


def workspace_corpus_has_files(wd: Path) -> bool:
    """True if ``wd`` looks like a populated workspace corpus tree."""
    return _workspace_corpus_has_files(wd)


def openai_api_key() -> str:
    from app.config import get_settings

    return get_settings().resolve_llm_api_key()


def openai_base_url() -> str | None:
    from app.config import get_settings

    return get_settings().openai_base_url_optional()


def embedding_model() -> str:
    from app.config import get_settings

    return get_settings().embedding_model.strip() or "text-embedding-3-small"


# Globs relative to ``corpus_data_root()`` (workspace or legacy ``data/``).
CORPUS_RELATIVE_PATTERNS: list[tuple[str, str]] = [
    ("runbook", "runbooks/**/*.md"),
    ("incident", "incidents/incident-*.md"),
    ("incident", "incidents/sample-incident.md"),
    ("log", "logs/*.log"),
    ("knowledge", "knowledge_base/**/*.md"),
]

# ADR / decision docs stay at repository root (not duplicated under workspace ``data/``).
CORPUS_PROJECT_PATTERNS: list[tuple[str, str]] = [
    ("decision", "docs/decisions/**/*.md"),
]

# Back-compat name for scripts / docs (same as ``CORPUS_RELATIVE_PATTERNS``).
CORPUS_GLOBS = CORPUS_RELATIVE_PATTERNS
