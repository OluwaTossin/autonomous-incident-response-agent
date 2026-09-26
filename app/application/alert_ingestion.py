"""Authenticated, tenant-resolved CloudWatch alarm ingestion."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol, Self
from uuid import NAMESPACE_URL, uuid5

from app.application.aws_integrations import AwsIntegrationRepository
from app.application.incidents import (
    AuditEventRepository,
    IncidentRepository,
    TriageRunRepository,
)
from app.application.jobs import (
    JobDispatchRepository,
    JobRepository,
    TriageJobPayload,
    job_payload_hash,
)
from app.auth.context import ActorContext
from app.authorization.permissions import Permission
from app.authorization.service import AuthorizationService, AuthorizedTenantContext
from app.domain.alert_ingestion import (
    AlertEventReceipt,
    AlertReceiptStatus,
    AwsAlarmCurrentState,
    CloudWatchAlarmEvent,
    CloudWatchAlarmValue,
)
from app.domain.aws_integrations import AwsCapability, AwsIntegrationState
from app.domain.common import (
    ActorKind,
    CorrelationContext,
    OrganizationScope,
    WorkspaceScope,
)
from app.domain.events import AuditEvent
from app.domain.identifiers import (
    AlertReceiptId,
    AuditEventId,
    AwsAlarmStateId,
    CorrelationId,
    IncidentId,
    IntegrationId,
    JobId,
    OrganizationId,
    TriageRunId,
    WorkspaceId,
)
from app.domain.incidents import (
    Incident,
    IncidentSource,
    IncidentState,
    TriageRun,
    TriageRunState,
)
from app.domain.operations import Job, JobKind, JobState
from app.domain.usage import QuotaExceeded, QuotaType, UsageType
from app.models.incident import IncidentPayload


class AlertIngestionNotFound(LookupError):
    pass


class AlertIngestionDenied(PermissionError):
    pass


class AlertIngestionConflict(RuntimeError):
    pass


class AlertIngestionOutcome(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    IGNORED = "ignored"


@dataclass(frozen=True, slots=True)
class AlertIngestionResult:
    outcome: AlertIngestionOutcome
    receipt_id: AlertReceiptId
    incident_id: IncidentId | None
    triage_run_id: TriageRunId | None


class AlertReceiptRepository(Protocol):
    def create_or_get(
        self, receipt: AlertEventReceipt
    ) -> tuple[AlertEventReceipt, bool]: ...
    def save(self, receipt: AlertEventReceipt) -> None: ...


class AlarmStateRepository(Protocol):
    def lock_identity(self, integration_id: IntegrationId, identity_hash: str) -> None: ...
    def get(
        self, integration_id: IntegrationId, identity_hash: str
    ) -> AwsAlarmCurrentState | None: ...
    def add(self, state: AwsAlarmCurrentState) -> None: ...
    def save(self, state: AwsAlarmCurrentState) -> None: ...


class AlertIngestionUnitOfWork(Protocol):
    aws_integrations: AwsIntegrationRepository
    alert_receipts: AlertReceiptRepository
    alarm_states: AlarmStateRepository
    incidents: IncidentRepository
    triage_runs: TriageRunRepository
    jobs: JobRepository
    dispatches: JobDispatchRepository
    audit_events: AuditEventRepository
    usage: object

    def __enter__(self) -> Self: ...
    def __exit__(self, exc_type, exc_value, traceback) -> None: ...


class AlertIngestionObserver(Protocol):
    def record(self, event: str, duration_ms: int, outcome: str) -> None: ...


class NoopAlertIngestionObserver:
    def record(self, event: str, duration_ms: int, outcome: str) -> None:
        return None


class HostedAlertIngestionService:
    def __init__(
        self,
        authorization: AuthorizationService,
        uow_factory: Callable[[AuthorizedTenantContext], AlertIngestionUnitOfWork],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
        observer: AlertIngestionObserver = NoopAlertIngestionObserver(),
        future_tolerance: timedelta = timedelta(minutes=5),
        enforce_quotas: bool = False,
    ) -> None:
        self._authorization = authorization
        self._uow_factory = uow_factory
        self._clock = clock
        self._monotonic = monotonic
        self._observer = observer
        self._future_tolerance = future_tolerance
        self._enforce_quotas = enforce_quotas

    def ingest(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        integration_id: IntegrationId,
        event: CloudWatchAlarmEvent,
    ) -> AlertIngestionResult:
        context = self._authorize_machine(
            actor, organization_id, workspace_id
        )
        try:
            request_correlation_id = CorrelationId(actor.request_id or "")
        except ValueError:
            request_correlation_id = CorrelationId.new()
        now = self._clock()
        if event.observed_at > now + self._future_tolerance:
            raise AlertIngestionConflict("Alarm event time is unreasonably far in the future")
        started = self._monotonic()
        try:
            with self._uow_factory(context) as uow:
                integration = uow.aws_integrations.get(integration_id)
                if integration is None:
                    raise AlertIngestionNotFound("AWS integration not found")
                if integration.scope != WorkspaceScope(organization_id, workspace_id):
                    raise AlertIngestionNotFound("AWS integration not found")
                self._validate_integration(integration, event)

                receipt = AlertEventReceipt(
                    id=AlertReceiptId.new(),
                    scope=integration.scope,
                    integration_id=integration.id,
                    event_id=event.event_id,
                    payload_hash=event.payload_hash,
                    alarm_identity=event.alarm_identity,
                    alarm_identity_hash=event.alarm_identity_hash,
                    alarm_name=event.alarm_name,
                    account_id=event.account_id,
                    region=event.region,
                    state=event.state,
                    previous_state=event.previous_state,
                    observed_at=event.observed_at,
                    received_at=now,
                    status=AlertReceiptStatus.ACCEPTED,
                    created_by=context.actor,
                )
                persisted, created = uow.alert_receipts.create_or_get(receipt)
                if not created:
                    if persisted.payload_hash != receipt.payload_hash:
                        raise AlertIngestionConflict(
                            "EventBridge event id is already bound to different content"
                        )
                    uow.audit_events.add(
                        _audit(
                            context,
                            "alarm_event.duplicate",
                            "alert_event_receipt",
                            str(persisted.id),
                            now,
                            event,
                        )
                    )
                    result = AlertIngestionResult(
                        AlertIngestionOutcome.DUPLICATE,
                        persisted.id,
                        persisted.incident_id,
                        persisted.triage_run_id,
                    )
                else:
                    try:
                        if self._enforce_quotas:
                            uow.usage.decision(
                                QuotaType.ALERT_EVENTS_PER_HOUR, 1, at=now
                            )
                    except QuotaExceeded:
                        ignored = receipt.processed(AlertReceiptStatus.IGNORED_POLICY)
                        uow.alert_receipts.save(ignored)
                        uow.audit_events.add(
                            _audit(
                                context,
                                "alarm_event.quota_rejected",
                                "alert_event_receipt",
                                str(receipt.id),
                                now,
                                event,
                            )
                        )
                        result = AlertIngestionResult(
                            AlertIngestionOutcome.IGNORED, receipt.id, None, None
                        )
                    else:
                        if self._enforce_quotas:
                            uow.usage.record(
                                UsageType.ALERT_EVENT_ACCEPTED,
                                1,
                                source="eventbridge",
                                source_reference=event.event_id,
                                correlation=CorrelationContext(request_correlation_id),
                                actor=context.actor,
                                at=now,
                                resource_type="alert_event_receipt",
                                resource_id=str(receipt.id),
                            )
                        result = self._process_new(
                            uow,
                            context,
                            integration.id,
                            receipt,
                            event,
                            now,
                            request_correlation_id,
                        )
        except Exception:
            self._observer.record(
                "alarm_ingestion_failure",
                int((self._monotonic() - started) * 1000),
                "failed",
            )
            raise
        self._observer.record(
            "alarm_events_received",
            int((self._monotonic() - started) * 1000),
            result.outcome.value,
        )
        self._observer.record(
            f"alert_events_{result.outcome.value}",
            int((self._monotonic() - started) * 1000),
            result.outcome.value,
        )
        return result

    def _process_new(
        self,
        uow: AlertIngestionUnitOfWork,
        context: AuthorizedTenantContext,
        integration_id: IntegrationId,
        receipt: AlertEventReceipt,
        event: CloudWatchAlarmEvent,
        now: datetime,
        request_correlation_id: CorrelationId,
    ) -> AlertIngestionResult:
        uow.alarm_states.lock_identity(integration_id, event.alarm_identity_hash)
        current = uow.alarm_states.get(integration_id, event.alarm_identity_hash)
        if current is not None and (
            event.observed_at,
            event.event_id,
        ) <= (
            current.latest_observed_at,
            current.latest_event_id,
        ):
            ignored = receipt.processed(AlertReceiptStatus.IGNORED_STALE)
            uow.alert_receipts.save(ignored)
            uow.audit_events.add(
                _audit(
                    context,
                    "alarm_event.stale_ignored",
                    "alert_event_receipt",
                    str(receipt.id),
                    now,
                    event,
                )
            )
            return AlertIngestionResult(
                AlertIngestionOutcome.IGNORED, receipt.id, None, None
            )

        incident = self._active_incident(uow, current)
        triage_run_id: TriageRunId | None = None
        status = AlertReceiptStatus.ACCEPTED
        if event.state is CloudWatchAlarmValue.ALARM:
            if incident is None:
                incident, triage_run_id = self._create_incident_and_triage(
                    uow, context, integration_id, event, now, request_correlation_id
                )
            else:
                status = AlertReceiptStatus.IGNORED_POLICY
        elif event.state is CloudWatchAlarmValue.OK:
            if incident is not None and incident.state in {
                IncidentState.OPEN,
                IncidentState.INVESTIGATING,
            }:
                incident = incident.transition(IncidentState.RESOLVED, at=now)
                uow.incidents.save(incident)
                uow.audit_events.add(
                    _audit(
                        context,
                        "alarm_event.recovery_applied",
                        "incident",
                        str(incident.id),
                        now,
                        event,
                    )
                )
            else:
                status = AlertReceiptStatus.IGNORED_POLICY
        else:
            status = AlertReceiptStatus.IGNORED_POLICY

        incident_id = incident.id if incident is not None else None
        updated_receipt = receipt.processed(
            status, incident_id=incident_id, triage_run_id=triage_run_id
        )
        uow.alert_receipts.save(updated_receipt)
        next_state = (
            current.advance(event, at=now, incident_id=incident_id)
            if current is not None
            else AwsAlarmCurrentState(
                id=AwsAlarmStateId.new(),
                scope=receipt.scope,
                integration_id=integration_id,
                alarm_identity=event.alarm_identity,
                alarm_identity_hash=event.alarm_identity_hash,
                alarm_name=event.alarm_name,
                latest_event_id=event.event_id,
                latest_state=event.state,
                latest_observed_at=event.observed_at,
                updated_at=now,
                incident_id=incident_id,
            )
        )
        if current is None:
            uow.alarm_states.add(next_state)
        else:
            uow.alarm_states.save(next_state)
        uow.audit_events.add(
            _audit(
                context,
                (
                    "alarm_event.accepted"
                    if status is AlertReceiptStatus.ACCEPTED
                    else "alarm_event.policy_ignored"
                ),
                "alert_event_receipt",
                str(receipt.id),
                now,
                event,
            )
        )
        return AlertIngestionResult(
            (
                AlertIngestionOutcome.ACCEPTED
                if status is AlertReceiptStatus.ACCEPTED
                else AlertIngestionOutcome.IGNORED
            ),
            receipt.id,
            incident_id,
            triage_run_id,
        )

    @staticmethod
    def _active_incident(uow, current) -> Incident | None:
        if current is None or current.incident_id is None:
            return None
        incident = uow.incidents.get(current.incident_id, for_update=True)
        if incident is None or incident.state in {IncidentState.RESOLVED, IncidentState.CLOSED}:
            return None
        return incident

    @staticmethod
    def _validate_integration(integration, event: CloudWatchAlarmEvent) -> None:
        if integration.state is not AwsIntegrationState.READY:
            raise AlertIngestionConflict("AWS integration is not ready for alarm delivery")
        if event.account_id != integration.aws_account_id:
            raise AlertIngestionConflict("Alarm event account does not match integration")
        if event.region not in integration.enabled_regions:
            raise AlertIngestionConflict("Alarm event region is not configured")
        verification = integration.verification
        alarm_verified = verification is not None and any(
            check.capability is AwsCapability.CLOUDWATCH_ALARMS_READ
            and check.region == event.region
            and check.passed
            for check in verification.checks
        )
        if not alarm_verified:
            raise AlertIngestionConflict("AWS integration is not ready for alarm delivery")

    def _create_incident_and_triage(
        self,
        uow: AlertIngestionUnitOfWork,
        context: AuthorizedTenantContext,
        integration_id: IntegrationId,
        event: CloudWatchAlarmEvent,
        now: datetime,
        request_correlation_id: CorrelationId,
    ) -> tuple[Incident, TriageRunId]:
        incident_id = IncidentId.new()
        run_id = TriageRunId(
            str(uuid5(NAMESPACE_URL, f"aira:alarm-triage:{integration_id}:{event.event_id}"))
        )
        job_id = JobId.new()
        correlation = CorrelationContext(
            request_correlation_id,
            incident_id=incident_id,
            triage_run_id=run_id,
            job_id=job_id,
        )
        incident = Incident(
            id=incident_id,
            scope=WorkspaceScope(context.organization_id, context.workspace_id),
            payload=IncidentPayload.model_validate(
                {
                    "alert_title": event.alarm_name,
                    "service_name": "aws-cloudwatch",
                    "environment": event.region,
                    "logs": event.reason,
                    "metric_summary": (
                        f"CloudWatch alarm changed from {event.previous_state.value} "
                        f"to {event.state.value} in {event.region}."
                    ),
                    "time_of_occurrence": event.observed_at.isoformat(),
                    "severity_hint": "HIGH",
                }
            ),
            source=IncidentSource(
                provider="aws.cloudwatch",
                source_type="alarm_state_change",
                received_at=now,
                external_id=f"cw:{integration_id}:{event.event_id}",
            ),
            state=IncidentState.OPEN,
            created_by=context.actor,
            created_at=now,
            updated_at=now,
            correlation=correlation,
        )
        resolved_incident, created = uow.incidents.create_or_get(incident)
        if not created:
            raise AlertIngestionConflict("Alarm transition incident already exists")
        run = TriageRun(
            id=run_id,
            scope=resolved_incident.scope,
            incident=resolved_incident.reference,
            state=TriageRunState.QUEUED,
            created_by=context.actor,
            created_at=now,
            updated_at=now,
            correlation=correlation,
        )
        payload = TriageJobPayload(resolved_incident.id, run_id)
        metadata = payload.metadata()
        job = Job(
            id=job_id,
            scope=resolved_incident.scope,
            kind=JobKind.TRIAGE,
            subject_type=payload.subject_type,
            subject_id=payload.subject_id,
            state=JobState.PENDING,
            created_by=context.actor,
            created_at=now,
            updated_at=now,
            correlation=correlation,
            idempotency_key=f"alarm:{integration_id}:{event.event_id}",
            payload_version=payload.schema_version,
            payload=metadata,
            payload_hash=job_payload_hash(payload.kind, payload.schema_version, metadata),
            available_at=now,
            max_attempts=3,
        )
        resolved_job, job_created = uow.jobs.create_or_get(job)
        if not job_created or resolved_job.payload_hash != job.payload_hash:
            raise AlertIngestionConflict("Alarm transition triage already exists")
        uow.triage_runs.add(run)
        uow.dispatches.add(resolved_job, at=now)
        uow.audit_events.add(
            _audit(
                context,
                "incident.created",
                "incident",
                str(resolved_incident.id),
                now,
                event,
            )
        )
        uow.audit_events.add(
            _audit(
                context,
                "triage.requested",
                "triage_run",
                str(run.id),
                now,
                event,
            )
        )
        return resolved_incident, run.id

    def _authorize_machine(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
    ) -> AuthorizedTenantContext:
        if actor.actor.kind not in {ActorKind.SERVICE_ACCOUNT, ActorKind.SYSTEM}:
            raise AlertIngestionDenied("Machine authentication required")
        context = self._authorization.authorize(
            actor,
            organization_id,
            Permission.INCIDENT_CREATE,
            workspace_id=workspace_id,
        )
        for permission in (
            Permission.INTEGRATION_READ,
            Permission.TRIAGE_RUN,
            Permission.JOB_CREATE,
        ):
            self._authorization.authorize(
                actor, organization_id, permission, workspace_id=workspace_id
            )
        return context


def _audit(
    context: AuthorizedTenantContext,
    event_type: str,
    target_type: str,
    target_id: str,
    at: datetime,
    event: CloudWatchAlarmEvent,
) -> AuditEvent:
    return AuditEvent(
        id=AuditEventId.new(),
        organization_scope=OrganizationScope(context.organization_id),
        workspace_scope=WorkspaceScope(context.organization_id, context.workspace_id),
        event_type=event_type,
        target_type=target_type,
        target_id=target_id,
        actor=context.actor,
        occurred_at=at,
        correlation=CorrelationContext(CorrelationId.new()),
        details=tuple(
            sorted(
                {
                    "provider": "aws.cloudwatch",
                    "alarm_state": event.state.value,
                    "region": event.region,
                    "event_id": event.event_id,
                }.items()
            )
        ),
    )
