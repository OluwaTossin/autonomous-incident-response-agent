"""Integration and asynchronous job domain concepts without provider adapters."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

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


class JobErrorCategory(StrEnum):
    TRANSIENT = "transient"
    VALIDATION = "validation"
    AUTHORIZATION = "authorization"
    CONFIGURATION = "configuration"
    INTERNAL = "internal"


_INTEGRATION_TRANSITIONS = {
    IntegrationState.ACTIVE: frozenset({IntegrationState.DISABLED, IntegrationState.ERROR}),
    IntegrationState.DISABLED: frozenset({IntegrationState.ACTIVE}),
    IntegrationState.ERROR: frozenset({IntegrationState.ACTIVE, IntegrationState.DISABLED}),
}

JOB_TERMINAL_STATES = frozenset({JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class JobFailure:
    code: str
    category: JobErrorCategory
    retryable: bool
    summary: str

    def __post_init__(self) -> None:
        for name, value, maximum in (
            ("code", self.code, 120),
            ("summary", self.summary, 1000),
        ):
            normalized = value.strip()
            if not normalized or len(normalized) > maximum or any(
                character in normalized for character in "\r\n"
            ):
                raise DomainInvariantError(f"Job failure {name} is invalid")
            object.__setattr__(self, name, normalized)
        if self.retryable is not (self.category is JobErrorCategory.TRANSIENT):
            raise DomainInvariantError(
                "Only transient job failures may be marked retryable"
            )


@dataclass(frozen=True, slots=True)
class JobResultReference:
    result_type: str
    result_id: str
    metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _validate_metadata("result", self.metadata)
        normalized_type = self.result_type.strip()
        normalized_id = self.result_id.strip()
        if (
            not normalized_type
            or len(normalized_type) > 80
            or any(character in normalized_type for character in "\r\n")
        ):
            raise DomainInvariantError("Job result type is invalid")
        if (
            not normalized_id
            or len(normalized_id) > 255
            or any(character in normalized_id for character in "\r\n")
        ):
            raise DomainInvariantError("Job result id is invalid")
        object.__setattr__(self, "result_type", normalized_type)
        object.__setattr__(self, "result_id", normalized_id)


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
    idempotency_key: str
    payload_version: int
    payload: tuple[tuple[str, str], ...]
    payload_hash: str
    available_at: datetime
    attempt_count: int = 0
    max_attempts: int = 3
    state_version: int = 1
    dispatch_generation: int = 1
    claimed_by: str | None = None
    claim_token: UUID | None = None
    lease_expires_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancellation_requested_at: datetime | None = None
    last_error: JobFailure | None = None
    result: JobResultReference | None = None

    def __post_init__(self) -> None:
        if not self.subject_type.strip() or not self.subject_id.strip():
            raise DomainInvariantError("Job subject_type and subject_id cannot be blank")
        key = self.idempotency_key.strip()
        if not key or len(key) > 255 or any(character in key for character in "\r\n"):
            raise DomainInvariantError("Job idempotency_key is invalid")
        object.__setattr__(self, "idempotency_key", key)
        if self.payload_version < 1:
            raise DomainInvariantError("Job payload_version must be positive")
        _validate_metadata("payload", self.payload)
        if not _SHA256_RE.fullmatch(self.payload_hash):
            raise DomainInvariantError("Job payload_hash must be lowercase SHA-256")
        if self.max_attempts < 1 or not 0 <= self.attempt_count <= self.max_attempts:
            raise DomainInvariantError("Job attempt counts are invalid")
        if self.state_version < 1 or self.dispatch_generation < 1:
            raise DomainInvariantError("Job version counters must be positive")
        if self.correlation.job_id not in (None, self.id):
            raise DomainInvariantError("Job correlation references another job")
        validate_timestamps(self.created_at, self.updated_at)
        for name, value in (
            ("available_at", self.available_at),
            ("lease_expires_at", self.lease_expires_at),
            ("started_at", self.started_at),
            ("completed_at", self.completed_at),
            ("failed_at", self.failed_at),
            ("cancelled_at", self.cancelled_at),
            ("cancellation_requested_at", self.cancellation_requested_at),
        ):
            if value is not None:
                require_aware(value, name)
        if self.available_at < self.created_at:
            raise DomainInvariantError("Job available_at cannot precede created_at")
        if self.started_at is not None and self.started_at < self.created_at:
            raise DomainInvariantError("Job started_at cannot precede created_at")
        if self.completed_at is not None and self.completed_at < (self.started_at or self.created_at):
            raise DomainInvariantError("Job completed_at cannot precede its start")
        if self.claimed_by is not None:
            worker_id = self.claimed_by.strip()
            if (
                not worker_id
                or len(worker_id) > 120
                or any(character in worker_id for character in "\r\n")
            ):
                raise DomainInvariantError("Job claimed_by is invalid")
            object.__setattr__(self, "claimed_by", worker_id)
        self._validate_state_shape()

    def _validate_state_shape(self) -> None:
        claim_values = (self.claimed_by, self.claim_token, self.lease_expires_at)
        has_claim = all(value is not None for value in claim_values)
        if any(value is not None for value in claim_values) and not has_claim:
            raise DomainInvariantError("Job claim metadata must be complete")
        if self.state is JobState.PENDING:
            if has_claim or any((self.completed_at, self.cancelled_at, self.result)):
                raise DomainInvariantError("Pending job lifecycle fields are inconsistent")
        elif self.state is JobState.RUNNING:
            if not has_claim or self.started_at is None or any(
                (self.completed_at, self.cancelled_at, self.result)
            ):
                raise DomainInvariantError("Running job lifecycle fields are inconsistent")
        elif self.state is JobState.SUCCEEDED:
            if (
                has_claim
                or self.started_at is None
                or self.completed_at is None
                or self.result is None
            ):
                raise DomainInvariantError("Succeeded jobs require a compact result reference")
            if any((self.failed_at, self.cancelled_at, self.last_error)):
                raise DomainInvariantError("Succeeded jobs cannot carry failure state")
        elif self.state is JobState.FAILED:
            if (
                has_claim
                or self.completed_at is None
                or self.failed_at is None
                or self.last_error is None
            ):
                raise DomainInvariantError("Failed jobs require safe failure metadata")
        elif self.state is JobState.CANCELLED:
            if has_claim or self.completed_at is None or self.cancelled_at is None:
                raise DomainInvariantError("Cancelled jobs require cancellation timestamps")

    def claim(
        self,
        *,
        worker_id: str,
        claim_token: UUID,
        lease_expires_at: datetime,
        at: datetime | None = None,
    ) -> Job:
        when = at or utc_now()
        if self.state is not JobState.PENDING or self.available_at > when:
            raise DomainInvariantError("Job is not runnable")
        if self.attempt_count >= self.max_attempts:
            raise DomainInvariantError("Job has exhausted its attempts")
        if lease_expires_at <= when:
            raise DomainInvariantError("Job lease must expire after claim time")
        return replace(
            self,
            state=JobState.RUNNING,
            claimed_by=worker_id,
            claim_token=claim_token,
            lease_expires_at=lease_expires_at,
            started_at=when,
            attempt_count=self.attempt_count + 1,
            state_version=self.state_version + 1,
            updated_at=when,
        )

    def succeed(
        self,
        claim_token: UUID,
        result: JobResultReference,
        *,
        at: datetime | None = None,
    ) -> Job:
        when = at or utc_now()
        self._require_active_claim(claim_token, when)
        if self.cancellation_requested_at is not None:
            raise DomainInvariantError("Job cancellation must be acknowledged")
        return replace(
            self,
            state=JobState.SUCCEEDED,
            completed_at=when,
            updated_at=when,
            state_version=self.state_version + 1,
            claimed_by=None,
            claim_token=None,
            lease_expires_at=None,
            cancellation_requested_at=None,
            last_error=None,
            failed_at=None,
            result=result,
        )

    def renew_lease(
        self,
        claim_token: UUID,
        *,
        lease_expires_at: datetime,
        at: datetime | None = None,
    ) -> Job:
        when = at or utc_now()
        self._require_active_claim(claim_token, when)
        require_aware(lease_expires_at, "lease_expires_at")
        if lease_expires_at <= when:
            raise DomainInvariantError("Renewed job lease must expire in the future")
        return replace(
            self,
            lease_expires_at=lease_expires_at,
            state_version=self.state_version + 1,
            updated_at=when,
        )

    def fail_attempt(
        self,
        claim_token: UUID,
        failure: JobFailure,
        *,
        next_available_at: datetime,
        at: datetime | None = None,
    ) -> Job:
        when = at or utc_now()
        self._require_active_claim(claim_token, when)
        require_aware(next_available_at, "next_available_at")
        retry = failure.retryable and self.attempt_count < self.max_attempts
        if retry and next_available_at < when:
            raise DomainInvariantError("Retry availability cannot precede failure")
        return replace(
            self,
            state=JobState.PENDING if retry else JobState.FAILED,
            available_at=next_available_at if retry else self.available_at,
            completed_at=None if retry else when,
            failed_at=when,
            updated_at=when,
            state_version=self.state_version + 1,
            dispatch_generation=self.dispatch_generation + (1 if retry else 0),
            claimed_by=None,
            claim_token=None,
            lease_expires_at=None,
            cancellation_requested_at=None,
            last_error=failure,
        )

    def request_cancel(self, *, at: datetime | None = None) -> Job:
        when = at or utc_now()
        if self.state is JobState.PENDING:
            return replace(
                self,
                state=JobState.CANCELLED,
                completed_at=when,
                cancelled_at=when,
                updated_at=when,
                state_version=self.state_version + 1,
            )
        if self.state is JobState.RUNNING:
            if self.cancellation_requested_at is not None:
                return self
            return replace(
                self,
                cancellation_requested_at=when,
                updated_at=when,
                state_version=self.state_version + 1,
            )
        raise DomainInvariantError("Terminal jobs cannot be cancelled")

    def acknowledge_cancellation(
        self,
        claim_token: UUID,
        *,
        at: datetime | None = None,
    ) -> Job:
        when = at or utc_now()
        self._require_active_claim(claim_token, when)
        if self.cancellation_requested_at is None:
            raise DomainInvariantError("Job cancellation was not requested")
        return replace(
            self,
            state=JobState.CANCELLED,
            completed_at=when,
            cancelled_at=when,
            updated_at=when,
            state_version=self.state_version + 1,
            claimed_by=None,
            claim_token=None,
            lease_expires_at=None,
        )

    def recover_expired(
        self,
        failure: JobFailure,
        *,
        next_available_at: datetime,
        at: datetime | None = None,
    ) -> Job:
        when = at or utc_now()
        if (
            self.state is not JobState.RUNNING
            or self.lease_expires_at is None
            or self.lease_expires_at > when
        ):
            raise DomainInvariantError("Job lease is not expired")
        if self.cancellation_requested_at is not None:
            return replace(
                self,
                state=JobState.CANCELLED,
                completed_at=when,
                cancelled_at=when,
                updated_at=when,
                state_version=self.state_version + 1,
                claimed_by=None,
                claim_token=None,
                lease_expires_at=None,
            )
        retry = failure.retryable and self.attempt_count < self.max_attempts
        return replace(
            self,
            state=JobState.PENDING if retry else JobState.FAILED,
            available_at=next_available_at if retry else self.available_at,
            completed_at=None if retry else when,
            failed_at=when,
            updated_at=when,
            state_version=self.state_version + 1,
            dispatch_generation=self.dispatch_generation + (1 if retry else 0),
            claimed_by=None,
            claim_token=None,
            lease_expires_at=None,
            cancellation_requested_at=None,
            last_error=failure,
        )

    def _require_active_claim(self, claim_token: UUID, at: datetime) -> None:
        if (
            self.state is not JobState.RUNNING
            or self.claim_token != claim_token
            or self.lease_expires_at is None
            or self.lease_expires_at <= at
        ):
            raise DomainInvariantError("Job claim is stale or invalid")


def _validate_metadata(name: str, values: tuple[tuple[str, str], ...]) -> None:
    if len(values) > 32 or len({key for key, _ in values}) != len(values):
        raise DomainInvariantError(f"Job {name} metadata is invalid")
    for key, value in values:
        if (
            not key.strip()
            or len(key) > 80
            or len(value) > 1000
            or any(character in key + value for character in "\r\n")
        ):
            raise DomainInvariantError(f"Job {name} metadata is invalid")
