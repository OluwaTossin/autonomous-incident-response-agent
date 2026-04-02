"""FastAPI app: health, version, ingest, triage."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from pydantic import ValidationError

from app.agent.graph import run_triage
from app.agent.nodes import parse_incident_payload

# Keep in sync with pyproject [project].version
SERVICE_VERSION = "0.1.0"

app = FastAPI(
    title="Autonomous Incident Response API",
    version=SERVICE_VERSION,
    description="Incident ingest and LangGraph triage with RAG (Phase 5).",
)


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
    """Run retrieval + LangGraph agent; return structured triage JSON."""
    _validate_incident_body(body)
    return run_triage(body)
