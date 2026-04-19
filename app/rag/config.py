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
    from app.config import get_settings

    rel = get_settings().rag_index_dir.strip() or ".rag_index"
    p = Path(rel)
    if not p.is_absolute():
        p = project_root() / p
    return p


def openai_api_key() -> str:
    from app.config import get_settings

    return get_settings().resolve_llm_api_key()


def openai_base_url() -> str | None:
    from app.config import get_settings

    return get_settings().openai_base_url_optional()


def embedding_model() -> str:
    from app.config import get_settings

    return get_settings().embedding_model.strip() or "text-embedding-3-small"


# Corpus roots relative to project root
CORPUS_GLOBS: list[tuple[str, str]] = [
    ("runbook", "data/runbooks/**/*.md"),
    ("incident", "data/incidents/incident-*.md"),
    ("incident", "data/incidents/sample-incident.md"),
    ("log", "data/logs/*.log"),
    ("knowledge", "data/knowledge_base/**/*.md"),
    ("decision", "docs/decisions/**/*.md"),
]
