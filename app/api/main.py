"""FastAPI app: health, version, ingest, triage."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from pydantic import ValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse
from starlette.routing import Mount

_log = logging.getLogger(__name__)

from app.agent.nodes import parse_incident_payload
from app.api.n8n_routes import router as n8n_router
from app.api.triage_execution import run_full_triage

# Keep in sync with pyproject [project].version
SERVICE_VERSION = "0.1.0"

app = FastAPI(
    title="Autonomous Incident Response API",
    version=SERVICE_VERSION,
    description="Incident ingest and LangGraph triage with RAG (Phase 5–7).",
)

app.include_router(n8n_router)


def _gradio_ui_mounted(application: FastAPI) -> bool:
    """True if Gradio is mounted at ``/ui`` (``uv sync --extra ui`` + ENABLE_GRADIO_UI)."""
    return any(isinstance(r, Mount) and getattr(r, "path", None) == "/ui" for r in application.routes)


@app.get("/")
def root(request: Request) -> dict[str, Any]:
    """Helps confirm you hit this app (not another process on :8000)."""
    return {
        "service": "autonomous-incident-response-agent",
        "version": SERVICE_VERSION,
        "docs": "/docs",
        "health": "/health",
        "version_path": "/version",
        "ingest": "POST /ingest-incident",
        "triage": "POST /triage",
        "n8n_mock_jira": "POST /n8n/mock-jira/issue",
        "n8n_workflow_log": "POST /n8n/workflow-log",
        "n8n_triage_feedback": "POST /n8n/triage-feedback",
        "gradio_ui": "/ui",
        "gradio_ui_mounted": _gradio_ui_mounted(request.app),
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/version")
def version() -> dict[str, str]:
    return {
        "version": SERVICE_VERSION,
        "service": "autonomous-incident-response-agent",
    }


def _validate_incident_body(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=422,
            detail="Request body must be a JSON object",
        )
    try:
        payload = parse_incident_payload(body)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors()) from e
    return payload.model_dump(mode="json")


@app.post("/ingest-incident")
def ingest_incident(
    body: dict[str, Any] = Body(
        ...,
        examples={
            "minimal": {
                "summary": "Minimal incident",
                "value": {"alert_title": "HighCPU", "service_name": "payment-api"},
            },
        },
    ),
) -> dict[str, Any]:
    """
    Validate and normalize an incident payload (webhook-style intake).
    Does not run the LLM; use `POST /triage` for full triage.
    """
    normalized = _validate_incident_body(body)
    return {
        "status": "accepted",
        "received_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "normalized": normalized,
    }


@app.post("/triage")
def post_triage(
    body: dict[str, Any] = Body(
        ...,
        examples={
            "payment_cpu": {
                "summary": "Sample payment-api CPU alert",
                "value": {
                    "alert_title": "HighCPU on payment-api",
                    "service_name": "payment-api",
                    "environment": "production",
                    "metric_summary": "CPU 94%, p99 latency 820ms",
                    "logs": "WARN fraud-module timeout",
                    "time_of_occurrence": "2026-04-10T14:05:00Z",
                },
            },
        },
    ),
) -> dict[str, Any]:
    """Run retrieval + LangGraph agent; return structured triage JSON with ``triage_id`` for feedback join."""
    incident = _validate_incident_body(body)
    return run_full_triage(incident)


def _with_optional_gradio(application: FastAPI) -> FastAPI:
    if os.environ.get("ENABLE_GRADIO_UI", "1").lower() in ("0", "false", "no"):
        return application
    try:
        from app.ui.gradio_app import with_gradio_ui

        return with_gradio_ui(application)
    except ImportError as e:
        _log.warning("Gradio UI skipped — run `uv sync --extra ui`. (%s)", e)
        return application
    except Exception:
        _log.exception("Gradio UI failed to mount; REST API still available.")
        return application


app = _with_optional_gradio(app)


class _RedirectUiSlashMiddleware(BaseHTTPMiddleware):
    """Gradio static assets expect ``/ui/``; browsers often open ``/ui`` first."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.scope.get("path") == "/ui":
            base = str(request.base_url)
            if not base.endswith("/"):
                base = base + "/"
            return RedirectResponse(url=f"{base}ui/", status_code=307)
        return await call_next(request)


app.add_middleware(_RedirectUiSlashMiddleware)
