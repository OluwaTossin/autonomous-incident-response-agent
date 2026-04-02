"""Inbound incident payload (aligns with docs/decisions/problem-definition.md)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class IncidentPayload(BaseModel):
    alert_title: str = Field(default="", description="Short title from alerting system")
    service_name: str = Field(default="", description="Logical service id, e.g. payment-api")
    environment: str = Field(default="", description="dev | staging | production")
    logs: str = Field(default="", description="Relevant log excerpts")
    metric_summary: str = Field(default="", description="Key metrics / thresholds")
    time_of_occurrence: str = Field(default="", description="ISO 8601 or human time")

    model_config = {"extra": "allow"}
