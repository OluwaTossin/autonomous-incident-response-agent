"""Append-only JSONL audit log for triage API (Phase 5 → 6 handoff)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.rag.config import project_root

logger = logging.getLogger(__name__)


def triage_audit_path() -> Path:
    custom = get_settings().triage_audit_jsonl.strip()
    root = project_root()
    if custom:
        p = Path(custom)
        return p if p.is_absolute() else (root / p)
    return root / "data" / "logs" / "triage_outputs.jsonl"


def top_k_sources_from_hits(hits: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Stable summary for audit / eval (sorted by score descending)."""
    if not hits:
        return []
    rows: list[dict[str, Any]] = []
    for h in hits:
        if not isinstance(h, dict):
            continue
        try:
            score = float(h.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        rows.append(
            {
                "source": str(h.get("source") or ""),
                "doc_type": str(h.get("doc_type") or ""),
                "score": round(score, 6),
                "chunk_index": h.get("chunk_index"),
            }
        )
    rows.sort(key=lambda r: (-r["score"], r["source"]))
    return rows


def _truncated_rag_context(text: str) -> str:
    raw = get_settings().triage_audit_max_rag_chars.strip() or "200000"
    try:
        max_c = int(raw)
    except ValueError:
        max_c = 200_000
    if max_c <= 0 or len(text) <= max_c:
        return text
    return text[:max_c] + "\n…[truncated: TRIAGE_AUDIT_MAX_RAG_CHARS]"


def append_triage_jsonl(
    payload: dict[str, Any],
    result: dict[str, Any],
    *,
    triage_id: str,
    rag_context: str | None = None,
    retrieval_hits: list[dict[str, Any]] | None = None,
) -> None:
    """
    Append one JSON line: triage_id, timestamp, input, output, retrieved_context, top_k_sources.

    `triage_id` must match the id returned on `POST /triage` and referenced by feedback rows.

    Never raises to callers. Does not log API keys (only request body you send — scrub payloads).
    """
    if get_settings().triage_audit_disable.strip().lower() in ("1", "true", "yes"):
        return
    path = triage_audit_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        ctx = rag_context if isinstance(rag_context, str) else ""
        entry = {
            "triage_id": triage_id,
            "timestamp": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "input": payload,
            "output": result,
            "retrieved_context": _truncated_rag_context(ctx),
            "top_k_sources": top_k_sources_from_hits(retrieval_hits),
        }
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError as e:
        logger.warning("triage audit log write failed (%s): %s", path, e)
