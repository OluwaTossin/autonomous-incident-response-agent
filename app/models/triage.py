"""Structured triage output (execution.md Phase 4)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class TriageOutput(BaseModel):
    incident_summary: str = Field(..., min_length=1)
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    likely_root_cause: str = Field(..., min_length=1)
    recommended_actions: list[str] = Field(..., min_length=1)
    escalate: bool
    confidence: float = Field(..., ge=0.0, le=1.0)

    @field_validator("recommended_actions")
    @classmethod
    def strip_actions(cls, v: list[str]) -> list[str]:
        out = [a.strip() for a in v if a and str(a).strip()]
        if not out:
            raise ValueError("At least one non-empty recommended action required")
        return out
