"""Structured triage output (Phase 4 agent + Phase 5 API)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


EvidenceType = Literal[
    "log",
    "incident",
    "runbook",
    "knowledge",
    "decision",
    "metric",
    "alert",
    "other",
]


class EvidenceItem(BaseModel):
    """Explicit attribution: which corpus or payload slice supports a conclusion."""

    type: EvidenceType
    source: str = Field(..., min_length=1, description="Filename, path, or stable source id")
    reason: str = Field(..., min_length=1, description="Why this evidence supports the triage")


class TriageOutput(BaseModel):
    incident_summary: str = Field(..., min_length=1)
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    likely_root_cause: str = Field(..., min_length=1)
    recommended_actions: list[str] = Field(..., min_length=1)
    escalate: bool
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: list[EvidenceItem] = Field(
        default_factory=list,
        description="Citations tying conclusions to retrieval sources and payload excerpts",
    )
    conflicting_signals_summary: str | None = Field(
        default=None,
        description="If signals conflict (e.g. CPU vs DB exhaustion), say so; null if aligned",
    )
    timeline: list[str] = Field(
        default_factory=list,
        description="Ordered event strings (relative T+n or ISO) from payload/logs",
    )

    @field_validator("recommended_actions")
    @classmethod
    def strip_actions(cls, v: list[str]) -> list[str]:
        out = [a.strip() for a in v if a and str(a).strip()]
        if not out:
            raise ValueError("At least one non-empty recommended action required")
        return out

    @field_validator("timeline")
    @classmethod
    def strip_timeline(cls, v: list[str]) -> list[str]:
        return [str(x).strip() for x in v if x and str(x).strip()]

    @field_validator("conflicting_signals_summary")
    @classmethod
    def strip_conflict(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        return s or None
