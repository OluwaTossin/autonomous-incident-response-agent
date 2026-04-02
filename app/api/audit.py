"""Append-only JSONL audit log for triage API (Phase 5 → 6 handoff)."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.rag.config import project_root

logger = logging.getLogger(__name__)


def triage_audit_path() -> Path:
    custom = os.environ.get("TRIAGE_AUDIT_JSONL", "").strip()
    root = project_root()
    if custom:
        p = Path(custom)
        return p if p.is_absolute() else (root / p)
    return root / "data" / "logs" / "triage_outputs.jsonl"


def append_triage_jsonl(payload: dict[str, Any], result: dict[str, Any]) -> None:
    """Append one JSON line: timestamp, input, output. Never raises to callers."""
    if os.environ.get("TRIAGE_AUDIT_DISABLE", "").lower() in ("1", "true", "yes"):
        return
    path = triage_audit_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "input": payload,
            "output": result,
        }
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError as e:
        logger.warning("triage audit log write failed (%s): %s", path, e)
