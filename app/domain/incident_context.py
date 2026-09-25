"""Bounded, incident-specific operational context for hosted triage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.domain.common import DomainInvariantError, WorkspaceScope, require_aware
from app.domain.identifiers import (
    IncidentContextItemId,
    IncidentContextSnapshotId,
    IncidentId,
    IntegrationId,
    TriageRunId,
)


class ContextCollectionStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"


class ContextItemType(StrEnum):
    ALARM = "aws_cloudwatch_alarm"
    METRIC = "aws_cloudwatch_metric"
    LOG = "aws_cloudwatch_log"


class CollectorStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NOT_CONFIGURED = "not_configured"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class CollectorDiagnostic:
    collector: str
    status: CollectorStatus
    code: str | None = None
    summary: str | None = None

    def __post_init__(self) -> None:
        if self.collector not in {"alarm", "metrics", "logs"}:
            raise DomainInvariantError("Context collector is invalid")
        if (self.code is None) is not (self.summary is None):
            raise DomainInvariantError(
                "Collector diagnostic error metadata must be complete"
            )
        if self.summary is not None and len(self.summary) > 500:
            raise DomainInvariantError("Collector diagnostic summary is too long")


@dataclass(frozen=True, slots=True)
class IncidentContextItem:
    id: IncidentContextItemId
    snapshot_id: IncidentContextSnapshotId
    scope: WorkspaceScope
    type: ContextItemType
    source: str
    observed_at: datetime
    content: dict[str, Any]
    sequence: int
    truncated: bool = False

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "observed_at")
        if not self.source.strip() or len(self.source) > 1000:
            raise DomainInvariantError("Context item source is invalid")
        if self.sequence < 0:
            raise DomainInvariantError("Context item sequence cannot be negative")
        if not isinstance(self.content, dict):
            raise DomainInvariantError("Context item content must be an object")


@dataclass(frozen=True, slots=True)
class IncidentContextSnapshot:
    id: IncidentContextSnapshotId
    scope: WorkspaceScope
    incident_id: IncidentId
    triage_run_id: TriageRunId
    integration_id: IntegrationId
    provider: str
    region: str
    window_start: datetime
    window_end: datetime
    collected_at: datetime
    status: ContextCollectionStatus
    policy_version: str
    diagnostics: tuple[CollectorDiagnostic, ...]
    items: tuple[IncidentContextItem, ...]
    truncated: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("window_start", self.window_start),
            ("window_end", self.window_end),
            ("collected_at", self.collected_at),
        ):
            require_aware(value, name)
        if self.window_end < self.window_start:
            raise DomainInvariantError("Context collection window is invalid")
        if self.provider != "aws.cloudwatch":
            raise DomainInvariantError("Unsupported context provider")
        if not self.region or len(self.region) > 64:
            raise DomainInvariantError("Context region is invalid")
        if not self.policy_version or len(self.policy_version) > 80:
            raise DomainInvariantError("Context policy version is invalid")
        for sequence, item in enumerate(self.items):
            if item.snapshot_id != self.id or item.scope != self.scope:
                raise DomainInvariantError(
                    "Context item does not belong to its snapshot"
                )
            if item.sequence != sequence:
                raise DomainInvariantError(
                    "Context items must have contiguous sequence values"
                )
