"""Integration and asynchronous job domain concepts without provider adapters."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from app.domain.common import (
    ActorReference,
    CorrelationContext,
    DomainInvariantError,
    WorkspaceScope,
    require_aware,
    require_transition,
    utc_now,
    validate_timestamps,
)
from app.domain.identifiers import IntegrationId, JobId


class IntegrationState(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    ERROR = "error"


class JobKind(StrEnum):
    TRIAGE = "triage"
    INDEX_BUILD = "index_build"
    CONTEXT_COLLECTION = "context_collection"
    ACTION_EXECUTION = "action_execution"


class JobState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


_INTEGRATION_TRANSITIONS = {
    IntegrationState.ACTIVE: frozenset({IntegrationState.DISABLED, IntegrationState.ERROR}),
    IntegrationState.DISABLED: frozenset({IntegrationState.ACTIVE}),
    IntegrationState.ERROR: frozenset({IntegrationState.ACTIVE, IntegrationState.DISABLED}),
}

_JOB_TRANSITIONS = {
    JobState.PENDING: frozenset({JobState.RUNNING, JobState.CANCELLED}),
    JobState.RUNNING: frozenset({JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}),
    JobState.SUCCEEDED: frozenset(),
    JobState.FAILED: frozenset(),
    JobState.CANCELLED: frozenset(),
}

JOB_TERMINAL_STATES = frozenset({JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED})


@dataclass(frozen=True, slots=True)
class Integration:
    id: IntegrationId
    scope: WorkspaceScope
    provider: str
    name: str
    state: IntegrationState
    created_by: ActorReference
    created_at: datetime
    updated_at: datetime
    last_error: str | None = None

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.name.strip():
            raise DomainInvariantError("Integration provider and name cannot be blank")
        validate_timestamps(self.created_at, self.updated_at)
        if self.state is IntegrationState.ERROR and not self.last_error:
            raise DomainInvariantError("Error integrations require last_error")
        if self.state is not IntegrationState.ERROR and self.last_error is not None:
            raise DomainInvariantError("Only error integrations may carry last_error")

    def transition(
        self,
        target: IntegrationState,
        *,
        at: datetime | None = None,
        error: str | None = None,
    ) -> Integration:
        require_transition("Integration", self.state, target, _INTEGRATION_TRANSITIONS)
        normalized_error = error.strip() if error else None
        if target is IntegrationState.ERROR and not normalized_error:
            raise DomainInvariantError("Transition to integration error requires a reason")
        return replace(
            self,
            state=target,
            last_error=normalized_error if target is IntegrationState.ERROR else None,
            updated_at=at or utc_now(),
        )


@dataclass(frozen=True, slots=True)
class Job:
    id: JobId
    scope: WorkspaceScope
    kind: JobKind
    subject_type: str
    subject_id: str
    state: JobState
    created_by: ActorReference
    created_at: datetime
    updated_at: datetime
    correlation: CorrelationContext
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if not self.subject_type.strip() or not self.subject_id.strip():
            raise DomainInvariantError("Job subject_type and subject_id cannot be blank")
        if self.correlation.job_id not in (None, self.id):
            raise DomainInvariantError("Job correlation references another job")
        validate_timestamps(self.created_at, self.updated_at)
        for name, value in (("started_at", self.started_at), ("completed_at", self.completed_at)):
            if value is not None:
                require_aware(value, name)
        if self.started_at is not None and self.started_at < self.created_at:
            raise DomainInvariantError("Job started_at cannot precede created_at")
        if self.completed_at is not None and self.completed_at < (self.started_at or self.created_at):
            raise DomainInvariantError("Job completed_at cannot precede its start")
        self._validate_state_shape()

    def _validate_state_shape(self) -> None:
        if self.state is JobState.PENDING and any(
            (self.started_at, self.completed_at, self.error_message)
        ):
            raise DomainInvariantError("Pending jobs cannot have execution outcome fields")
        if self.state is JobState.RUNNING and (
            self.started_at is None or self.completed_at is not None or self.error_message is not None
        ):
            raise DomainInvariantError("Running jobs require only started_at")
        if self.state is JobState.SUCCEEDED and (
            self.started_at is None or self.completed_at is None or self.error_message is not None
        ):
            raise DomainInvariantError("Succeeded jobs require start and completion without error")
        if self.state is JobState.FAILED and (
            self.started_at is None or self.completed_at is None or not self.error_message
        ):
            raise DomainInvariantError("Failed jobs require start, completion, and error")
        if self.state is JobState.CANCELLED and self.completed_at is None:
            raise DomainInvariantError("Cancelled jobs require completed_at")

    def start(self, *, at: datetime | None = None) -> Job:
        target = JobState.RUNNING
        require_transition("Job", self.state, target, _JOB_TRANSITIONS)
        when = at or utc_now()
        return replace(self, state=target, started_at=when, updated_at=when)

    def succeed(self, *, at: datetime | None = None) -> Job:
        return self._complete(JobState.SUCCEEDED, at=at)

    def fail(self, error: str, *, at: datetime | None = None) -> Job:
        normalized = error.strip()
        if not normalized:
            raise DomainInvariantError("Failed jobs require a non-empty error")
        return self._complete(JobState.FAILED, at=at, error_message=normalized)

    def cancel(self, *, at: datetime | None = None) -> Job:
        return self._complete(JobState.CANCELLED, at=at)

    def _complete(
        self,
        target: JobState,
        *,
        at: datetime | None,
        error_message: str | None = None,
    ) -> Job:
        require_transition("Job", self.state, target, _JOB_TRANSITIONS)
        when = at or utc_now()
        return replace(
            self,
            state=target,
            completed_at=when,
            updated_at=when,
            error_message=error_message,
        )
