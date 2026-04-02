"""Shared Pydantic models."""

from app.models.incident import IncidentPayload
from app.models.triage import TriageOutput

__all__ = ["IncidentPayload", "TriageOutput"]
