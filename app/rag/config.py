"""Environment and path configuration for RAG."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load project root `.env` only — not `.env.example` (that file is a template for Git).
_root = Path(__file__).resolve().parents[2]
load_dotenv(_root / ".env", override=False)


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def rag_index_dir() -> Path:
    rel = os.environ.get("RAG_INDEX_DIR", ".rag_index")
    p = Path(rel)
    if not p.is_absolute():
        p = project_root() / p
    return p


def openai_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if key:
        return key
    raise RuntimeError(
        "No API key found. Copy .env.example to .env in the project root and set "
        "OPENAI_API_KEY (or OPENROUTER_API_KEY). Keys in .env.example are not loaded."
    )


def openai_base_url() -> str | None:
    base = os.environ.get("OPENAI_API_BASE", "").strip()
    return base or None


def embedding_model() -> str:
    return os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small").strip()


# Corpus roots relative to project root
CORPUS_GLOBS: list[tuple[str, str]] = [
    ("runbook", "data/runbooks/**/*.md"),
    ("incident", "data/incidents/incident-*.md"),
    ("incident", "data/incidents/sample-incident.md"),
    ("log", "data/logs/*.log"),
    ("knowledge", "data/knowledge_base/**/*.md"),
    ("decision", "docs/decisions/**/*.md"),
]
