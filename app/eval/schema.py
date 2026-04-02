"""Gold dataset row schema (JSONL)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GoldExpect(BaseModel):
    """Optional expectations; omit fields you do not want to assert."""

    severity: str | None = Field(default=None, description="Exact match (case-insensitive)")
    severity_any_of: list[str] | None = None
    escalate: bool | None = None
    min_actions: int | None = Field(default=None, ge=0)
    summary_contains_all: list[str] | None = None
    root_cause_contains_any: list[str] | None = None
    retrieval_source_contains_any: list[str] | None = Field(
        default=None,
        description="At least one retrieval hit source must contain one of these substrings",
    )
    min_top_retrieval_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Max similarity score among hits must be >= this",
    )


class GoldCase(BaseModel):
    id: str = Field(..., min_length=1)
    incident: dict[str, Any]
    expect: GoldExpect = Field(default_factory=GoldExpect)

    model_config = {"extra": "ignore"}
