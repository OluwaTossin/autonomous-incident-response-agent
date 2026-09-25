"""Hosted incident and asynchronous triage application boundary."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, Self
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5

from app.application.jobs import (
    AuditEventRepository,
    JobDispatchRepository,
    JobRepository,
    TriageJobPayload,
    job_payload_hash,
)
from app.auth.context import ActorContext
from app.authorization.permissions import Permission
from app.authorization.service import AuthorizationService, AuthorizedTenantContext
from app.domain.common import CorrelationContext, OrganizationScope, WorkspaceScope
from app.domain.events import AuditEvent
from app.domain.identifiers import (
    AuditEventId,
    CorrelationId,
    FeedbackId,
    IncidentId,
    JobId,
    OrganizationId,
    TriageRunId,
    WorkspaceId,
)
from app.domain.incidents import (
    Evidence,
    Feedback,
    Incident,
    IncidentSource,
    IncidentState,
    TriageRun,
    TriageRunState,
)
from app.domain.operations import Job, JobKind, JobState
from app.models.incident import IncidentPayload


class HostedIncidentNotFound(LookupError):
    pass


class HostedTriageNotFound(LookupError):
    pass


class HostedIncidentConflict(RuntimeError):
    pass


class HostedTriageConflict(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class HostedIncidentInput:
    title: str
    description: str
    service_name: str
    environment: str
    source_provider: str
    source_type: str
    observed_at: datetime
    external_event_id: str | None = None
    source_url: str | None = None
    severity_hint: str | None = None
    metric_summary: str = ""

    def __post_init__(self) -> None:
        for name, value, maximum in (
            ("title", self.title, 200),
            ("description", self.description, 4000),
            ("service_name", self.service_name, 200),
            ("environment", self.environment, 80),
            ("source_provider", self.source_provider, 80),
            ("source_type", self.source_type, 80),
            ("metric_summary", self.metric_summary, 2000),
        ):
            normalized = value.strip()
            if name != "metric_summary" and not normalized:
                raise ValueError(f"{name} cannot be blank")
            if len(normalized) > maximum:
                raise ValueError(f"{name} exceeds {maximum} characters")
            object.__setattr__(self, name, normalized)
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        if self.external_event_id is not None:
            value = self.external_event_id.strip()
            if not value or len(value) > 255:
                raise ValueError("external_event_id is invalid")
            object.__setattr__(self, "external_event_id", value)
        if self.source_url is not None:
            value = self.source_url.strip()
            parsed = urlparse(value)
            if len(value) > 1000 or parsed.scheme not in {"https", "http"}:
                raise ValueError("source_url must be a bounded HTTP(S) URL")
            object.__setattr__(self, "source_url", value)
        if self.severity_hint is not None:
            value = self.severity_hint.strip().upper()
            if value not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
                raise ValueError("severity_hint is invalid")
            object.__setattr__(self, "severity_hint", value)

    def payload(self) -> IncidentPayload:
        values = {
            "alert_title": self.title,
            "service_name": self.service_name,
            "environment": self.environment,
            "logs": self.description,
            "metric_summary": self.metric_summary,
            "time_of_occurrence": self.observed_at.isoformat(),
        }
        if self.severity_hint is not None:
            values["severity_hint"] = self.severity_hint
        return IncidentPayload.model_validate(values)


@dataclass(frozen=True, slots=True)
class IncidentListCursor:
    created_at: datetime
    incident_id: IncidentId


@dataclass(frozen=True, slots=True)
class TriageRunListCursor:
    created_at: datetime
    triage_run_id: TriageRunId


@dataclass(frozen=True, slots=True)
class TriageRequestResult:
    run: TriageRun
    job: Job
    created: bool


@dataclass(frozen=True, slots=True)
class TriageView:
    run: TriageRun
    job: Job
    evidence: tuple[Evidence, ...]


class IncidentRepository(Protocol):
    def create_or_get(self, incident: Incident) -> tuple[Incident, bool]: ...
    def get(self, incident_id: IncidentId, *, for_update: bool = False) -> Incident | None: ...
    def list(
        self,
        *,
        limit: int,
        before: IncidentListCursor | None,
        state: IncidentState | None = None,
    ) -> Sequence[Incident]: ...
    def save(self, incident: Incident) -> None: ...


class TriageRunRepository(Protocol):
    def add(self, run: TriageRun) -> None: ...
    def get(self, run_id: TriageRunId, *, for_update: bool = False) -> TriageRun | None: ...
    def list(
        self,
        *,
        limit: int,
        before: TriageRunListCursor | None,
        incident_id: IncidentId | None = None,
        state: TriageRunState | None = None,
    ) -> Sequence[TriageRun]: ...
    def save(self, run: TriageRun, *, expected_version: int) -> None: ...
    def list_inconsistent_jobs(self, *, limit: int): ...


class EvidenceRepository(Protocol):
    def list_for_run(self, run_id: TriageRunId) -> Sequence[Evidence]: ...
    def replace_for_run(self, run_id: TriageRunId, evidence: Sequence[Evidence]) -> None: ...


class FeedbackRepository(Protocol):
    def add(self, feedback: Feedback) -> None: ...


class HostedIncidentUnitOfWork(Protocol):
    incidents: IncidentRepository
    triage_runs: TriageRunRepository
    evidence: EvidenceRepository
    feedback: FeedbackRepository
    jobs: JobRepository
    dispatches: JobDispatchRepository
    audit_events: AuditEventRepository

    def __enter__(self) -> Self: ...
    def __exit__(self, exc_type, exc_value, traceback) -> None: ...


HostedIncidentUnitOfWorkFactory = Callable[
    [AuthorizedTenantContext], HostedIncidentUnitOfWork
]


class IncidentLifecycleObserver(Protocol):
    def record(self, event: str, duration_ms: int, outcome: str) -> None: ...


class NoopIncidentLifecycleObserver:
    def record(self, event: str, duration_ms: int, outcome: str) -> None:
        return None


class HostedIncidentService:
    def __init__(
        self,
        authorization: AuthorizationService,
        uow_factory: HostedIncidentUnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
        observer: IncidentLifecycleObserver = NoopIncidentLifecycleObserver(),
    ) -> None:
        self._authorization = authorization
        self._uow_factory = uow_factory
        self._clock = clock
        self._monotonic = monotonic
        self._observer = observer

    def create_incident(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        data: HostedIncidentInput,
    ) -> Incident:
        context = self._authorize(
            actor, organization_id, workspace_id, Permission.INCIDENT_CREATE
        )
        now = self._clock()
        incident_id = IncidentId.new()
        correlation = CorrelationContext(
            CorrelationId.new(), incident_id=incident_id
        )
        incident = Incident(
            id=incident_id,
            scope=WorkspaceScope(organization_id, workspace_id),
            payload=data.payload(),
            source=IncidentSource(
                provider=data.source_provider,
                source_type=data.source_type,
                received_at=now,
                external_id=data.external_event_id,
                source_url=data.source_url,
            ),
            state=IncidentState.OPEN,
            created_by=context.actor,
            created_at=now,
            updated_at=now,
            correlation=correlation,
        )
        started = self._monotonic()
        with self._uow_factory(context) as uow:
            resolved, created = uow.incidents.create_or_get(incident)
            if not created and resolved.to_legacy_payload() != incident.to_legacy_payload():
                raise HostedIncidentConflict(
                    "External event ID is already bound to different incident content"
                )
            if created:
                uow.audit_events.add(
                    _audit(context, resolved, "incident.created", now)
                )
        self._observe("incidents_created", started, "created" if created else "reused")
        return resolved

    def get_incident(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        incident_id: IncidentId,
    ) -> Incident:
        context = self._authorize(
            actor, organization_id, workspace_id, Permission.INCIDENT_READ
        )
        with self._uow_factory(context) as uow:
            incident = uow.incidents.get(incident_id)
            if incident is None:
                raise HostedIncidentNotFound("Incident not found")
            return incident

    def list_incidents(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        *,
        limit: int = 50,
        before: IncidentListCursor | None = None,
        state: IncidentState | None = None,
    ) -> tuple[Incident, ...]:
        if not 1 <= limit <= 101:
            raise ValueError("Incident list limit must be between 1 and 101")
        context = self._authorize(
            actor, organization_id, workspace_id, Permission.INCIDENT_READ
        )
        with self._uow_factory(context) as uow:
            return tuple(uow.incidents.list(limit=limit, before=before, state=state))

    def transition_incident(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        incident_id: IncidentId,
        target: IncidentState,
    ) -> Incident:
        context = self._authorize(
            actor, organization_id, workspace_id, Permission.INCIDENT_CREATE
        )
        now = self._clock()
        with self._uow_factory(context) as uow:
            current = uow.incidents.get(incident_id, for_update=True)
            if current is None:
                raise HostedIncidentNotFound("Incident not found")
            try:
                updated = current.transition(target, at=now)
            except Exception as exc:
                raise HostedIncidentConflict(
                    "Incident state transition is not allowed"
                ) from exc
            uow.incidents.save(updated)
            uow.audit_events.add(
                _audit(context, updated, "incident.state_changed", now)
            )
            return updated

    def request_triage(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        incident_id: IncidentId,
        *,
        idempotency_key: str,
        max_attempts: int = 3,
    ) -> TriageRequestResult:
        key = _validate_idempotency_key(idempotency_key)
        context = self._authorize(
            actor, organization_id, workspace_id, Permission.TRIAGE_RUN
        )
        self._authorization.authorize(
            actor,
            organization_id,
            Permission.JOB_CREATE,
            workspace_id=workspace_id,
        )
        if not 1 <= max_attempts <= 10:
            raise ValueError("max_attempts must be between 1 and 10")
        run_id = _idempotent_triage_run_id(
            organization_id, workspace_id, incident_id, key
        )
        job_id = JobId.new()
        now = self._clock()
        correlation = CorrelationContext(
            CorrelationId.new(),
            incident_id=incident_id,
            triage_run_id=run_id,
            job_id=job_id,
        )
        payload = TriageJobPayload(incident_id, run_id)
        metadata = payload.metadata()
        durable_key = _durable_triage_key(incident_id, key)
        job = Job(
            id=job_id,
            scope=WorkspaceScope(organization_id, workspace_id),
            kind=JobKind.TRIAGE,
            subject_type=payload.subject_type,
            subject_id=payload.subject_id,
            state=JobState.PENDING,
            created_by=context.actor,
            created_at=now,
            updated_at=now,
            correlation=correlation,
            idempotency_key=durable_key,
            payload_version=payload.schema_version,
            payload=metadata,
            payload_hash=job_payload_hash(payload.kind, payload.schema_version, metadata),
            available_at=now,
            max_attempts=max_attempts,
        )
        started = self._monotonic()
        with self._uow_factory(context) as uow:
            incident = uow.incidents.get(incident_id)
            if incident is None:
                raise HostedIncidentNotFound("Incident not found")
            run = TriageRun(
                id=run_id,
                scope=incident.scope,
                incident=incident.reference,
                state=TriageRunState.QUEUED,
                created_by=context.actor,
                created_at=now,
                updated_at=now,
                correlation=correlation,
            )
            resolved_job, created = uow.jobs.create_or_get(job)
            if resolved_job.payload_hash != job.payload_hash:
                raise HostedTriageConflict(
                    "Idempotency key is already bound to another triage request"
                )
            if created:
                uow.triage_runs.add(run)
                uow.dispatches.add(resolved_job, at=now)
                uow.audit_events.add(
                    _audit(context, run, "triage.requested", now, job_id=resolved_job.id)
                )
            else:
                resolved_run = uow.triage_runs.get(run_id)
                if resolved_run is None:
                    raise HostedTriageConflict("Idempotent triage state is incomplete")
                run = resolved_run
        self._observe("triage_requests", started, "created" if created else "reused")
        return TriageRequestResult(run, resolved_job, created)

    def get_triage(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        run_id: TriageRunId,
    ) -> TriageView:
        context = self._authorize(
            actor, organization_id, workspace_id, Permission.INCIDENT_READ
        )
        with self._uow_factory(context) as uow:
            run = uow.triage_runs.get(run_id)
            if run is None:
                raise HostedTriageNotFound("Triage run not found")
            job = uow.jobs.get_by_subject("triage_run", str(run.id))
            if job is None:
                raise HostedTriageConflict("Triage job is unavailable")
            evidence = tuple(uow.evidence.list_for_run(run.id))
            return TriageView(run, job, evidence)

    def list_triage_runs(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        *,
        limit: int = 50,
        before: TriageRunListCursor | None = None,
        incident_id: IncidentId | None = None,
        state: TriageRunState | None = None,
    ) -> tuple[TriageRun, ...]:
        if not 1 <= limit <= 101:
            raise ValueError("Triage-run list limit must be between 1 and 101")
        context = self._authorize(
            actor, organization_id, workspace_id, Permission.INCIDENT_READ
        )
        with self._uow_factory(context) as uow:
            return tuple(
                uow.triage_runs.list(
                    limit=limit,
                    before=before,
                    incident_id=incident_id,
                    state=state,
                )
            )

    def cancel_triage(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        run_id: TriageRunId,
    ) -> TriageView:
        context = self._authorize(
            actor, organization_id, workspace_id, Permission.JOB_CANCEL
        )
        now = self._clock()
        with self._uow_factory(context) as uow:
            run = uow.triage_runs.get(run_id, for_update=True)
            if run is None:
                raise HostedTriageNotFound("Triage run not found")
            job = uow.jobs.get_by_subject("triage_run", str(run.id), for_update=True)
            if job is None:
                raise HostedTriageConflict("Triage job is unavailable")
            try:
                updated_job = job.request_cancel(at=now)
            except Exception as exc:
                raise HostedTriageConflict("Triage run cannot be cancelled") from exc
            if updated_job is not job:
                uow.jobs.save(updated_job, expected_version=job.state_version)
            updated_run = run
            if updated_job.state is JobState.CANCELLED and run.state is TriageRunState.QUEUED:
                updated_run = run.cancel(at=now)
                uow.triage_runs.save(updated_run, expected_version=run.state_version)
                uow.audit_events.add(
                    _audit(context, updated_run, "triage.cancelled", now, job_id=job.id)
                )
        self._observer.record("triage_cancelled", 0, "requested")
        return TriageView(updated_run, updated_job, tuple())

    def submit_feedback(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        run_id: TriageRunId,
        *,
        diagnosis_correct: bool | None,
        actions_useful: bool | None,
        notes: str | None,
    ) -> Feedback:
        context = self._authorize(
            actor, organization_id, workspace_id, Permission.INCIDENT_READ
        )
        if notes is not None and len(notes) > 2000:
            raise ValueError("Feedback notes exceed 2000 characters")
        now = self._clock()
        with self._uow_factory(context) as uow:
            run = uow.triage_runs.get(run_id)
            if run is None:
                raise HostedTriageNotFound("Triage run not found")
            feedback = Feedback(
                id=FeedbackId.new(),
                scope=run.scope,
                triage_run=run.reference,
                submitted_by=context.actor,
                created_at=now,
                diagnosis_correct=diagnosis_correct,
                actions_useful=actions_useful,
                notes=notes,
            )
            uow.feedback.add(feedback)
            return feedback

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

    def _observe(self, event: str, started: float, outcome: str) -> None:
        self._observer.record(
            event, max(0, int((self._monotonic() - started) * 1000)), outcome
        )


def _validate_idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 160 or any(c in normalized for c in "\r\n"):
        raise ValueError("Idempotency key is invalid")
    return normalized


def _durable_triage_key(incident_id: IncidentId, key: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"incident:{incident_id}:triage:{digest}"


def _idempotent_triage_run_id(
    organization_id: OrganizationId,
    workspace_id: WorkspaceId,
    incident_id: IncidentId,
    key: str,
) -> TriageRunId:
    value = uuid5(
        NAMESPACE_URL,
        f"aira:{organization_id}:{workspace_id}:{incident_id}:triage:{key}",
    )
    return TriageRunId(str(value))


def _audit(
    context: AuthorizedTenantContext,
    target: Incident | TriageRun,
    event_type: str,
    at: datetime,
    *,
    job_id: JobId | None = None,
) -> AuditEvent:
    details = [("state", target.state.value)]
    if isinstance(target, TriageRun):
        details.append(("incident_id", str(target.incident.id)))
        details.append(("triage_run_id", str(target.id)))
    if job_id is not None:
        details.append(("job_id", str(job_id)))
    return AuditEvent(
        id=AuditEventId.new(),
        organization_scope=OrganizationScope(context.organization_id),
        workspace_scope=target.scope,
        event_type=event_type,
        target_type="triage_run" if isinstance(target, TriageRun) else "incident",
        target_id=str(target.id),
        actor=context.actor,
        occurred_at=at,
        correlation=target.correlation,
        details=tuple(details),
    )
