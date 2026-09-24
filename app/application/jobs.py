"""Transport-neutral durable hosted job lifecycle."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, Self
from uuid import UUID, uuid4

from app.auth.context import ActorContext
from app.authorization.permissions import Permission
from app.authorization.service import AuthorizationService, AuthorizedTenantContext
from app.domain.common import CorrelationContext, OrganizationScope, WorkspaceScope
from app.domain.events import AuditEvent
from app.domain.identifiers import (
    AuditEventId,
    CorrelationId,
    JobId,
    KnowledgeIndexVersionId,
    OrganizationId,
    WorkspaceId,
)
from app.domain.operations import (
    Job,
    JobErrorCategory,
    JobFailure,
    JobKind,
    JobResultReference,
    JobState,
)


class JobNotFound(LookupError):
    """The authorized tenant cannot resolve the requested job."""


class JobConflict(RuntimeError):
    """The requested job operation conflicts with durable state."""


class JobIdempotencyConflict(JobConflict):
    """An idempotency key was reused with a different payload."""


class JobNotClaimable(JobConflict):
    """The job is not currently eligible for this claim or transition."""


@dataclass(frozen=True, slots=True)
class KnowledgeIndexBuildJobPayload:
    knowledge_index_version_id: KnowledgeIndexVersionId
    schema_version: int = 1

    @property
    def kind(self) -> JobKind:
        return JobKind.INDEX_BUILD

    @property
    def subject_type(self) -> str:
        return "knowledge_index_version"

    @property
    def subject_id(self) -> str:
        return str(self.knowledge_index_version_id)

    def metadata(self) -> tuple[tuple[str, str], ...]:
        if self.schema_version != 1:
            raise ValueError("Unsupported knowledge-index job payload version")
        return (("knowledge_index_version_id", self.subject_id),)


@dataclass(frozen=True, slots=True)
class JobListCursor:
    created_at: datetime
    job_id: JobId


@dataclass(frozen=True, slots=True)
class JobDispatch:
    id: UUID
    job_id: JobId
    dispatch_generation: int
    available_at: datetime
    created_at: datetime
    published_at: datetime | None = None


class JobRepository(Protocol):
    def create_or_get(self, job: Job) -> tuple[Job, bool]: ...
    def get(self, job_id: JobId, *, for_update: bool = False) -> Job | None: ...
    def list(
        self,
        *,
        limit: int,
        before: JobListCursor | None,
    ) -> Sequence[Job]: ...
    def list_expired(
        self,
        *,
        at: datetime,
        limit: int,
    ) -> Sequence[Job]: ...
    def save(self, job: Job, *, expected_version: int) -> None: ...


class JobDispatchRepository(Protocol):
    def add(self, job: Job, *, at: datetime) -> None: ...
    def list_unpublished(self, *, at: datetime, limit: int) -> Sequence[JobDispatch]: ...
    def mark_published(self, dispatch_id: UUID, *, at: datetime) -> bool: ...


class AuditEventRepository(Protocol):
    def add(self, event: AuditEvent) -> None: ...


class JobUnitOfWork(Protocol):
    jobs: JobRepository
    dispatches: JobDispatchRepository
    audit_events: AuditEventRepository

    def __enter__(self) -> Self: ...
    def __exit__(self, exc_type, exc_value, traceback) -> None: ...


JobUnitOfWorkFactory = Callable[[AuthorizedTenantContext], JobUnitOfWork]


class JobLifecycleObserver(Protocol):
    def record(self, event: str, duration_ms: int, outcome: str) -> None: ...


class NoopJobLifecycleObserver:
    def record(self, event: str, duration_ms: int, outcome: str) -> None:
        return None


class HostedJobService:
    def __init__(
        self,
        authorization: AuthorizationService,
        uow_factory: JobUnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
        token_factory: Callable[[], UUID] = uuid4,
        observer: JobLifecycleObserver = NoopJobLifecycleObserver(),
        retry_base: timedelta = timedelta(seconds=30),
        retry_max: timedelta = timedelta(minutes=15),
    ) -> None:
        if retry_base <= timedelta(0) or retry_max < retry_base:
            raise ValueError("Job retry bounds are invalid")
        self._authorization = authorization
        self._uow_factory = uow_factory
        self._clock = clock
        self._monotonic = monotonic
        self._token_factory = token_factory
        self._observer = observer
        self._retry_base = retry_base
        self._retry_max = retry_max

    def create_index_build_job(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        payload: KnowledgeIndexBuildJobPayload,
        *,
        idempotency_key: str,
        max_attempts: int = 3,
        available_at: datetime | None = None,
        correlation: CorrelationContext | None = None,
    ) -> Job:
        context = self._authorize(
            actor, organization_id, workspace_id, Permission.JOB_CREATE
        )
        now = self._clock()
        job_id = JobId.new()
        metadata = payload.metadata()
        job = Job(
            id=job_id,
            scope=WorkspaceScope(organization_id, workspace_id),
            kind=payload.kind,
            subject_type=payload.subject_type,
            subject_id=payload.subject_id,
            state=JobState.PENDING,
            created_by=actor.actor,
            created_at=now,
            updated_at=now,
            correlation=_job_correlation(correlation, job_id),
            idempotency_key=idempotency_key,
            payload_version=payload.schema_version,
            payload=metadata,
            payload_hash=_payload_hash(payload.kind, payload.schema_version, metadata),
            available_at=available_at or now,
            max_attempts=max_attempts,
        )
        started = self._monotonic()
        with self._uow_factory(context) as uow:
            resolved, created = uow.jobs.create_or_get(job)
            if resolved.payload_hash != job.payload_hash:
                raise JobIdempotencyConflict(
                    "Idempotency key is already bound to a different job payload"
                )
            if created:
                uow.dispatches.add(resolved, at=now)
                self._audit(uow, context, resolved, "job.created", now)
        self._observe("jobs_created", started, "created" if created else "reused")
        return resolved

    def get_job(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        job_id: JobId,
    ) -> Job:
        context = self._authorize(actor, organization_id, workspace_id, Permission.JOB_READ)
        with self._uow_factory(context) as uow:
            return self._required(uow.jobs.get(job_id))

    def list_jobs(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        *,
        limit: int = 50,
        before: JobListCursor | None = None,
    ) -> tuple[Job, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("Job list limit must be between 1 and 100")
        context = self._authorize(actor, organization_id, workspace_id, Permission.JOB_READ)
        with self._uow_factory(context) as uow:
            return tuple(uow.jobs.list(limit=limit, before=before))

    def claim_job(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        job_id: JobId,
        *,
        worker_id: str,
        lease_duration: timedelta,
    ) -> Job:
        if lease_duration <= timedelta(0):
            raise ValueError("Job lease duration must be positive")
        context = self._authorize(
            actor, organization_id, workspace_id, Permission.JOB_EXECUTE
        )
        now = self._clock()
        started = self._monotonic()
        with self._uow_factory(context) as uow:
            current = self._required(uow.jobs.get(job_id, for_update=True))
            try:
                claimed = current.claim(
                    worker_id=worker_id,
                    claim_token=self._token_factory(),
                    lease_expires_at=now + lease_duration,
                    at=now,
                )
            except Exception as exc:
                raise JobNotClaimable("Job is not currently claimable") from exc
            uow.jobs.save(claimed, expected_version=current.state_version)
            self._audit(uow, context, claimed, "job.claimed", now)
        self._observe("jobs_started", started, "succeeded")
        return claimed

    def complete_job(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        job_id: JobId,
        claim_token: UUID,
        result: JobResultReference,
    ) -> Job:
        return self._worker_transition(
            actor,
            organization_id,
            workspace_id,
            job_id,
            "job.succeeded",
            "jobs_succeeded",
            lambda current, now: current.succeed(claim_token, result, at=now),
        )

    def fail_job(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        job_id: JobId,
        claim_token: UUID,
        failure: JobFailure,
    ) -> Job:
        context = self._authorize(
            actor, organization_id, workspace_id, Permission.JOB_EXECUTE
        )
        now = self._clock()
        started = self._monotonic()
        with self._uow_factory(context) as uow:
            current = self._required(uow.jobs.get(job_id, for_update=True))
            next_available = now + self._backoff(current.attempt_count)
            try:
                updated = current.fail_attempt(
                    claim_token,
                    failure,
                    next_available_at=next_available,
                    at=now,
                )
            except Exception as exc:
                raise JobNotClaimable("Job failure claim is stale") from exc
            uow.jobs.save(updated, expected_version=current.state_version)
            if updated.state is JobState.PENDING:
                uow.dispatches.add(updated, at=now)
                event_type = "job.retry_scheduled"
                metric = "jobs_retried"
            else:
                event_type = "job.failed"
                metric = "jobs_failed"
            self._audit(uow, context, updated, event_type, now)
        self._observe(metric, started, "succeeded")
        return updated

    def cancel_job(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        job_id: JobId,
    ) -> Job:
        context = self._authorize(
            actor, organization_id, workspace_id, Permission.JOB_CANCEL
        )
        now = self._clock()
        started = self._monotonic()
        with self._uow_factory(context) as uow:
            current = self._required(uow.jobs.get(job_id, for_update=True))
            try:
                updated = current.request_cancel(at=now)
            except Exception as exc:
                raise JobConflict("Job cannot be cancelled") from exc
            if updated is not current:
                uow.jobs.save(updated, expected_version=current.state_version)
                event = (
                    "job.cancelled"
                    if updated.state is JobState.CANCELLED
                    else "job.cancellation_requested"
                )
                self._audit(uow, context, updated, event, now)
        self._observe("jobs_cancelled", started, "succeeded")
        return updated

    def acknowledge_cancellation(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        job_id: JobId,
        claim_token: UUID,
    ) -> Job:
        return self._worker_transition(
            actor,
            organization_id,
            workspace_id,
            job_id,
            "job.cancelled",
            "jobs_cancelled",
            lambda current, now: current.acknowledge_cancellation(
                claim_token, at=now
            ),
        )

    def recover_expired_jobs(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        *,
        limit: int = 100,
    ) -> tuple[Job, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("Recovery limit must be between 1 and 500")
        context = self._authorize(
            actor, organization_id, workspace_id, Permission.JOB_EXECUTE
        )
        now = self._clock()
        failure = JobFailure(
            "lease_expired",
            JobErrorCategory.TRANSIENT,
            True,
            "Worker lease expired before completion",
        )
        recovered: list[Job] = []
        with self._uow_factory(context) as uow:
            for current in uow.jobs.list_expired(at=now, limit=limit):
                updated = current.recover_expired(
                    failure,
                    next_available_at=now + self._backoff(current.attempt_count),
                    at=now,
                )
                uow.jobs.save(updated, expected_version=current.state_version)
                if updated.state is JobState.PENDING:
                    uow.dispatches.add(updated, at=now)
                self._audit(uow, context, updated, "job.lease_recovered", now)
                recovered.append(updated)
        if recovered:
            self._observer.record("lease_recovery", 0, "succeeded")
        return tuple(recovered)

    def list_unpublished_dispatches(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        *,
        limit: int = 100,
    ) -> tuple[JobDispatch, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("Dispatch list limit must be between 1 and 500")
        context = self._authorize(
            actor, organization_id, workspace_id, Permission.JOB_EXECUTE
        )
        with self._uow_factory(context) as uow:
            return tuple(
                uow.dispatches.list_unpublished(at=self._clock(), limit=limit)
            )

    def mark_dispatch_published(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        dispatch_id: UUID,
    ) -> bool:
        context = self._authorize(
            actor, organization_id, workspace_id, Permission.JOB_EXECUTE
        )
        with self._uow_factory(context) as uow:
            return uow.dispatches.mark_published(dispatch_id, at=self._clock())

    def _worker_transition(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        job_id: JobId,
        event_type: str,
        metric: str,
        transition: Callable[[Job, datetime], Job],
    ) -> Job:
        context = self._authorize(
            actor, organization_id, workspace_id, Permission.JOB_EXECUTE
        )
        now = self._clock()
        started = self._monotonic()
        with self._uow_factory(context) as uow:
            current = self._required(uow.jobs.get(job_id, for_update=True))
            try:
                updated = transition(current, now)
            except Exception as exc:
                raise JobNotClaimable("Job claim is stale") from exc
            uow.jobs.save(updated, expected_version=current.state_version)
            self._audit(uow, context, updated, event_type, now)
        self._observe(metric, started, "succeeded")
        return updated

    def _backoff(self, attempt_count: int) -> timedelta:
        multiplier = 2 ** max(0, attempt_count - 1)
        return min(self._retry_base * multiplier, self._retry_max)

    def _authorize(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        permission: Permission,
    ) -> AuthorizedTenantContext:
        return self._authorization.authorize(
            actor, organization_id, permission, workspace_id=workspace_id
        )

    @staticmethod
    def _required(job: Job | None) -> Job:
        if job is None:
            raise JobNotFound("Job not found")
        return job

    @staticmethod
    def _audit(
        uow: JobUnitOfWork,
        context: AuthorizedTenantContext,
        job: Job,
        event_type: str,
        at: datetime,
    ) -> None:
        details = [
            ("job_type", job.kind.value),
            ("attempt", str(job.attempt_count)),
            ("state", job.state.value),
        ]
        if job.last_error is not None:
            details.extend(
                (
                    ("error_code", job.last_error.code),
                    ("error_category", job.last_error.category.value),
                )
            )
        if job.result is not None:
            details.extend(
                (
                    ("result_type", job.result.result_type),
                    ("result_id", job.result.result_id),
                )
            )
        uow.audit_events.add(
            AuditEvent(
                id=AuditEventId.new(),
                organization_scope=OrganizationScope(context.organization_id),
                workspace_scope=job.scope,
                event_type=event_type,
                target_type="job",
                target_id=str(job.id),
                actor=context.actor,
                occurred_at=at,
                correlation=job.correlation,
                details=tuple(details),
            )
        )

    def _observe(self, event: str, started: float, outcome: str) -> None:
        duration_ms = max(0, int((self._monotonic() - started) * 1000))
        self._observer.record(event, duration_ms, outcome)


class KnowledgeIndexBuildOperation(Protocol):
    def build_publish_activate(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        *,
        index_version_id: KnowledgeIndexVersionId | None = None,
    ): ...


class TransientJobExecutionError(RuntimeError):
    """A deterministic adapter classification indicating bounded retry."""


class KnowledgeIndexBuildJobHandler:
    def __init__(
        self,
        jobs: HostedJobService,
        operation: KnowledgeIndexBuildOperation,
        *,
        lease_duration: timedelta = timedelta(minutes=15),
    ) -> None:
        self._jobs = jobs
        self._operation = operation
        self._lease_duration = lease_duration

    def execute(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        job_id: JobId,
        *,
        worker_id: str,
    ) -> Job:
        claimed = self._jobs.claim_job(
            actor,
            organization_id,
            workspace_id,
            job_id,
            worker_id=worker_id,
            lease_duration=self._lease_duration,
        )
        payload = dict(claimed.payload)
        index_version_id = KnowledgeIndexVersionId(
            payload["knowledge_index_version_id"]
        )
        try:
            published = self._operation.build_publish_activate(
                actor,
                organization_id,
                workspace_id,
                index_version_id=index_version_id,
            )
        except TransientJobExecutionError:
            return self._jobs.fail_job(
                actor,
                organization_id,
                workspace_id,
                job_id,
                claimed.claim_token,
                JobFailure(
                    "index_build_transient",
                    JobErrorCategory.TRANSIENT,
                    True,
                    "Knowledge index build encountered a transient dependency failure",
                ),
            )
        except Exception:
            return self._jobs.fail_job(
                actor,
                organization_id,
                workspace_id,
                job_id,
                claimed.claim_token,
                JobFailure(
                    "index_build_failed",
                    JobErrorCategory.INTERNAL,
                    False,
                    "Knowledge index build failed",
                ),
            )
        return self._jobs.complete_job(
            actor,
            organization_id,
            workspace_id,
            job_id,
            claimed.claim_token,
            JobResultReference(
                "knowledge_index_version",
                str(published.index.index_version_id),
            ),
        )


def _payload_hash(
    kind: JobKind,
    schema_version: int,
    metadata: tuple[tuple[str, str], ...],
) -> str:
    canonical = json.dumps(
        {
            "kind": kind.value,
            "schema_version": schema_version,
            "payload": dict(metadata),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _job_correlation(
    correlation: CorrelationContext | None,
    job_id: JobId,
) -> CorrelationContext:
    if correlation is None:
        return CorrelationContext(CorrelationId.new(), job_id=job_id)
    return CorrelationContext(
        correlation.correlation_id,
        incident_id=correlation.incident_id,
        triage_run_id=correlation.triage_run_id,
        job_id=job_id,
    )
