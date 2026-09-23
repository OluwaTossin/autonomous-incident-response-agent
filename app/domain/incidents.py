"""Hosted incident, triage, evidence, and feedback domain models."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.domain.common import (
    ActorReference,
    CorrelationContext,
    DataClassification,
    DomainInvariantError,
    RetentionMarker,
    WorkspaceScope,
    require_aware,
    require_transition,
    utc_now,
    validate_timestamps,
)
from app.domain.identifiers import EvidenceId, FeedbackId, IncidentId, TriageRunId
from app.models.incident import IncidentPayload
from app.models.triage import EvidenceItem, EvidenceType, TriageOutput


class IncidentState(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TriageRunState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


_INCIDENT_TRANSITIONS = {
    IncidentState.OPEN: frozenset(
        {IncidentState.INVESTIGATING, IncidentState.RESOLVED, IncidentState.CLOSED}
    ),
    IncidentState.INVESTIGATING: frozenset({IncidentState.RESOLVED, IncidentState.CLOSED}),
    IncidentState.RESOLVED: frozenset({IncidentState.CLOSED}),
    IncidentState.CLOSED: frozenset(),
}

_TRIAGE_TRANSITIONS = {
    TriageRunState.QUEUED: frozenset({TriageRunState.RUNNING, TriageRunState.CANCELLED}),
    TriageRunState.RUNNING: frozenset(
        {TriageRunState.SUCCEEDED, TriageRunState.FAILED, TriageRunState.CANCELLED}
    ),
    TriageRunState.SUCCEEDED: frozenset(),
    TriageRunState.FAILED: frozenset(),
    TriageRunState.CANCELLED: frozenset(),
}

TRIAGE_TERMINAL_STATES = frozenset(
    {TriageRunState.SUCCEEDED, TriageRunState.FAILED, TriageRunState.CANCELLED}
)


@dataclass(frozen=True, slots=True)
class IncidentSource:
    provider: str
    source_type: str
    received_at: datetime
    external_id: str | None = None
    source_url: str | None = None

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.source_type.strip():
            raise DomainInvariantError("Incident source provider and source_type cannot be blank")
        require_aware(self.received_at, "received_at")
        if self.external_id is not None and not self.external_id.strip():
            raise DomainInvariantError("Incident source external_id cannot be blank")


@dataclass(frozen=True, slots=True)
class IncidentReference:
    id: IncidentId
    scope: WorkspaceScope


@dataclass(frozen=True, slots=True)
class TriageRunReference:
    id: TriageRunId
    scope: WorkspaceScope


@dataclass(frozen=True, slots=True)
class Incident:
    id: IncidentId
    scope: WorkspaceScope
    payload: IncidentPayload
    source: IncidentSource
    state: IncidentState
    created_by: ActorReference
    created_at: datetime
    updated_at: datetime
    correlation: CorrelationContext
    classification: DataClassification = DataClassification.CONFIDENTIAL
    retention: RetentionMarker = RetentionMarker()

    def __post_init__(self) -> None:
        validate_timestamps(self.created_at, self.updated_at)
        if self.correlation.incident_id not in (None, self.id):
            raise DomainInvariantError("Incident correlation context references another incident")
        object.__setattr__(self, "payload", self.payload.model_copy(deep=True))

    @property
    def reference(self) -> IncidentReference:
        return IncidentReference(self.id, self.scope)

    def transition(
        self,
        target: IncidentState,
        *,
        at: datetime | None = None,
    ) -> Incident:
        require_transition("Incident", self.state, target, _INCIDENT_TRANSITIONS)
        return replace(self, state=target, updated_at=at or utc_now())

    def to_legacy_payload(self) -> dict[str, Any]:
        return self.payload.model_dump(mode="json")


@dataclass(frozen=True, slots=True)
class TriageRun:
    id: TriageRunId
    scope: WorkspaceScope
    incident: IncidentReference
    state: TriageRunState
    created_by: ActorReference
    created_at: datetime
    updated_at: datetime
    correlation: CorrelationContext
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: TriageOutput | None = None
    error_message: str | None = None
    classification: DataClassification = DataClassification.CONFIDENTIAL
    retention: RetentionMarker = RetentionMarker()

    def __post_init__(self) -> None:
        validate_timestamps(self.created_at, self.updated_at)
        if self.scope != self.incident.scope:
            raise DomainInvariantError("TriageRun and Incident must have the same workspace scope")
        if self.correlation.incident_id not in (None, self.incident.id):
            raise DomainInvariantError("TriageRun correlation references another incident")
        if self.correlation.triage_run_id not in (None, self.id):
            raise DomainInvariantError("TriageRun correlation references another triage run")
        for name, value in (("started_at", self.started_at), ("completed_at", self.completed_at)):
            if value is not None:
                require_aware(value, name)
        if self.started_at is not None and self.started_at < self.created_at:
            raise DomainInvariantError("started_at cannot precede created_at")
        if self.completed_at is not None:
            floor = self.started_at or self.created_at
            if self.completed_at < floor:
                raise DomainInvariantError("completed_at cannot precede the run start")
        self._validate_state_shape()

    def _validate_state_shape(self) -> None:
        if self.state is TriageRunState.QUEUED:
            if any((self.started_at, self.completed_at, self.result, self.error_message)):
                raise DomainInvariantError("Queued triage runs cannot have execution outcome fields")
        elif self.state is TriageRunState.RUNNING:
            if self.started_at is None or any((self.completed_at, self.result, self.error_message)):
                raise DomainInvariantError("Running triage runs require only started_at")
        elif self.state is TriageRunState.SUCCEEDED:
            if self.started_at is None or self.completed_at is None or self.result is None:
                raise DomainInvariantError("Succeeded triage runs require start, completion, and result")
            if self.error_message is not None:
                raise DomainInvariantError("Succeeded triage runs cannot have an error")
        elif self.state is TriageRunState.FAILED:
            if self.started_at is None or self.completed_at is None or not self.error_message:
                raise DomainInvariantError("Failed triage runs require start, completion, and error")
            if self.result is not None:
                raise DomainInvariantError("Failed triage runs cannot have a result")
        elif self.state is TriageRunState.CANCELLED:
            if self.completed_at is None or self.result is not None:
                raise DomainInvariantError("Cancelled triage runs require completion and no result")

    @property
    def reference(self) -> TriageRunReference:
        return TriageRunReference(self.id, self.scope)

    @property
    def legacy_triage_id(self) -> str:
        return self.id.to_legacy_triage_id()

    def start(self, *, at: datetime | None = None) -> TriageRun:
        target = TriageRunState.RUNNING
        require_transition("TriageRun", self.state, target, _TRIAGE_TRANSITIONS)
        when = at or utc_now()
        return replace(self, state=target, started_at=when, updated_at=when)

    def succeed(self, result: TriageOutput, *, at: datetime | None = None) -> TriageRun:
        target = TriageRunState.SUCCEEDED
        require_transition("TriageRun", self.state, target, _TRIAGE_TRANSITIONS)
        when = at or utc_now()
        return replace(
            self,
            state=target,
            result=result.model_copy(deep=True),
            completed_at=when,
            updated_at=when,
        )

    def fail(self, error_message: str, *, at: datetime | None = None) -> TriageRun:
        target = TriageRunState.FAILED
        require_transition("TriageRun", self.state, target, _TRIAGE_TRANSITIONS)
        error = error_message.strip()
        if not error:
            raise DomainInvariantError("Failed triage runs require a non-empty error")
        when = at or utc_now()
        return replace(
            self,
            state=target,
            error_message=error,
            completed_at=when,
            updated_at=when,
        )

    def cancel(self, *, at: datetime | None = None) -> TriageRun:
        target = TriageRunState.CANCELLED
        require_transition("TriageRun", self.state, target, _TRIAGE_TRANSITIONS)
        when = at or utc_now()
        return replace(self, state=target, completed_at=when, updated_at=when)

    def to_legacy_result(self) -> dict[str, Any]:
        if self.state is not TriageRunState.SUCCEEDED or self.result is None:
            raise DomainInvariantError("Only succeeded triage runs have a legacy result")
        return {
            **self.result.model_dump(mode="json"),
            "triage_id": self.legacy_triage_id,
        }


@dataclass(frozen=True, slots=True)
class Evidence:
    id: EvidenceId
    scope: WorkspaceScope
    triage_run: TriageRunReference
    type: EvidenceType
    source: str
    reason: str
    created_at: datetime
    classification: DataClassification = DataClassification.CONFIDENTIAL
    retention: RetentionMarker = RetentionMarker()

    def __post_init__(self) -> None:
        if self.scope != self.triage_run.scope:
            raise DomainInvariantError("Evidence and TriageRun must have the same workspace scope")
        require_aware(self.created_at, "created_at")
        EvidenceItem(type=self.type, source=self.source, reason=self.reason)

    def to_triage_item(self) -> EvidenceItem:
        return EvidenceItem(type=self.type, source=self.source, reason=self.reason)


@dataclass(frozen=True, slots=True)
class Feedback:
    id: FeedbackId
    scope: WorkspaceScope
    triage_run: TriageRunReference
    submitted_by: ActorReference
    created_at: datetime
    diagnosis_correct: bool | None = None
    actions_useful: bool | None = None
    notes: str | None = None
    classification: DataClassification = DataClassification.CONFIDENTIAL
    retention: RetentionMarker = RetentionMarker()

    def __post_init__(self) -> None:
        if self.scope != self.triage_run.scope:
            raise DomainInvariantError("Feedback and TriageRun must have the same workspace scope")
        require_aware(self.created_at, "created_at")
        if self.notes is not None:
            normalized = self.notes.strip()
            object.__setattr__(self, "notes", normalized or None)
