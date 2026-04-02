"""Mock Jira + workflow event log for n8n (Phase 6)."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body

from app.rag.config import project_root

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/n8n", tags=["n8n"])


def _workflow_log_path() -> Path:
    custom = os.environ.get("N8N_WORKFLOW_LOG_JSONL", "").strip()
    root = project_root()
    if custom:
        p = Path(custom)
        return p if p.is_absolute() else (root / p)
    return root / "data" / "logs" / "n8n_workflow_events.jsonl"


@router.post("/mock-jira/issue")
def mock_jira_issue(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    """
    Jira-style create-issue response for n8n HTTP Request node.
    Accepts any JSON; echoes summary/description if present.
    """
    suffix = uuid.uuid4().hex[:6].upper()
    key = f"MOCK-{suffix}"
    fields_in = body.get("fields")
    if isinstance(fields_in, dict):
        summary = str(fields_in.get("summary") or "Incident ticket")
        description = str(fields_in.get("description") or "")
    else:
        summary = str(body.get("summary") or "Incident ticket")
        description = str(body.get("description") or "")
    return {
        "key": key,
        "id": str(abs(hash(key)) % 9_999_999 + 1_000_000),
        "self": f"http://127.0.0.1:8000/n8n/mock-jira/issue/{key}",
        "fields": {"summary": summary, "description": description},
    }


@router.post("/workflow-log")
def workflow_log(event: dict[str, Any] = Body(...)) -> dict[str, str]:
    """
    Append one JSON line for n8n workflow diagnostics (Slack path + audit).
    Disable with N8N_WORKFLOW_LOG_DISABLE=1.
    """
    if os.environ.get("N8N_WORKFLOW_LOG_DISABLE", "").lower() in ("1", "true", "yes"):
        return {"status": "skipped"}
    path = _workflow_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            {
                "timestamp": datetime.now(UTC).replace(microsecond=0).isoformat(),
                "event": event,
            },
            ensure_ascii=False,
        ) + "\n"
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError as e:
        logger.warning("n8n workflow log write failed (%s): %s", path, e)
        return {"status": "error"}
    return {"status": "logged"}
