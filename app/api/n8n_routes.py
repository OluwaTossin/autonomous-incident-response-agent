"""Mock Jira + workflow event log for n8n (Phase 6)."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body

from app.config import get_settings
from app.rag.config import project_root

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/n8n", tags=["n8n"])


def _workflow_log_path() -> Path:
    custom = get_settings().n8n_workflow_log_jsonl.strip()
    root = project_root()
    if custom:
        p = Path(custom)
        return p if p.is_absolute() else (root / p)
    return root / "data" / "logs" / "n8n_workflow_events.jsonl"


def _triage_feedback_path() -> Path:
    custom = get_settings().n8n_triage_feedback_jsonl.strip()
    root = project_root()
    if custom:
        p = Path(custom)
        return p if p.is_absolute() else (root / p)
    return root / "data" / "logs" / "triage_feedback.jsonl"


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
    if get_settings().n8n_workflow_log_disable.strip().lower() in ("1", "true", "yes"):
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


def record_triage_feedback(event: dict[str, Any]) -> dict[str, str]:
    """
    Append one feedback JSONL line (same persistence as ``POST /n8n/triage-feedback``).

    Used by the HTTP route and the Phase 7 Gradio UI.
    """
    if get_settings().n8n_triage_feedback_disable.strip().lower() in ("1", "true", "yes"):
        return {"status": "skipped"}
    path = _triage_feedback_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tid = event.get("triage_id") if isinstance(event, dict) else None
        tid_str = str(tid).strip() if tid is not None and str(tid).strip() else None
        line = json.dumps(
            {
                "timestamp": datetime.now(UTC).replace(microsecond=0).isoformat(),
                "triage_id": tid_str,
                "feedback": event,
            },
            ensure_ascii=False,
        ) + "\n"
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError as e:
        logger.warning("n8n triage feedback write failed (%s): %s", path, e)
        return {"status": "error"}
    return {"status": "logged"}


@router.post("/triage-feedback")
def triage_feedback(event: dict[str, Any] = Body(...)) -> dict[str, str]:
    """
    Append human feedback after an escalation (diagnosis correct, actions useful, notes).

    Include **triage_id** (UUID from ``POST /triage``) so rows join to ``triage_outputs.jsonl``.
    Disable with N8N_TRIAGE_FEEDBACK_DISABLE=1.
    """
    return record_triage_feedback(event)
