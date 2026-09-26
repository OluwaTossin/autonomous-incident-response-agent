"""PostgreSQL transaction and repositories for CloudWatch alert ingestion."""

from __future__ import annotations

from types import TracebackType
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.authorization.service import AuthorizedTenantContext
from app.domain.alert_ingestion import (
    AlertEventReceipt,
    AlertReceiptStatus,
    AwsAlarmCurrentState,
    CloudWatchAlarmValue,
)
from app.domain.common import WorkspaceScope
from app.domain.identifiers import (
    AlertReceiptId,
    AwsAlarmStateId,
    IncidentId,
    IntegrationId,
    OrganizationId,
    TriageRunId,
    WorkspaceId,
)
from app.persistence.postgres.aws_integrations import PostgresAwsIntegrationRepository
from app.persistence.postgres.incident_repositories import (
    PostgresHostedIncidentRepository,
    PostgresTriageRunRepository,
)
from app.persistence.postgres.job_repositories import (
    PostgresJobDispatchRepository,
    PostgresJobRepository,
)
from app.persistence.postgres.mappers import _actor, _actor_columns
from app.persistence.postgres.models import (
    AlertEventReceiptRecord,
    AwsAlarmStateRecord,
)
from app.persistence.postgres.repositories import PostgresAuditEventRepository
from app.persistence.postgres.usage import PostgresUsageQuotaRepository
from app.persistence.postgres.tenant import TenantContext, apply_tenant_context


class PostgresAlertReceiptRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_or_get(
        self, receipt: AlertEventReceipt
    ) -> tuple[AlertEventReceipt, bool]:
        record = _receipt_to_record(receipt)
        values = {
            column.name: getattr(record, column.name)
            for column in AlertEventReceiptRecord.__table__.columns
        }
        inserted = self._session.scalar(
            insert(AlertEventReceiptRecord)
            .values(**values)
            .on_conflict_do_nothing(constraint="uq_alert_event_receipts_delivery")
            .returning(AlertEventReceiptRecord.id)
        )
        if inserted is not None:
            return receipt, True
        existing = self._session.scalar(
            select(AlertEventReceiptRecord).where(
                AlertEventReceiptRecord.integration_id
                == UUID(str(receipt.integration_id)),
                AlertEventReceiptRecord.event_id == receipt.event_id,
            )
        )
        if existing is None:
            raise RuntimeError("Concurrent alert receipt could not be resolved")
        return _receipt_from_record(existing), False

    def save(self, receipt: AlertEventReceipt) -> None:
        result = self._session.execute(
            update(AlertEventReceiptRecord)
            .where(AlertEventReceiptRecord.id == UUID(str(receipt.id)))
            .values(
                status=receipt.status.value,
                incident_id=(
                    UUID(str(receipt.incident_id)) if receipt.incident_id else None
                ),
                triage_run_id=(
                    UUID(str(receipt.triage_run_id)) if receipt.triage_run_id else None
                ),
            )
        )
        if result.rowcount != 1:
            raise RuntimeError("Alert receipt update conflicted")
        self._session.flush()

    def get_for_triage_run(self, run_id: TriageRunId) -> AlertEventReceipt | None:
        record = self._session.scalar(
            select(AlertEventReceiptRecord).where(
                AlertEventReceiptRecord.triage_run_id == UUID(str(run_id))
            )
        )
        return _receipt_from_record(record) if record is not None else None


class PostgresAlarmStateRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def lock_identity(self, integration_id: IntegrationId, identity_hash: str) -> None:
        key = f"{integration_id}:{identity_hash}"
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": key},
        )

    def get(
        self, integration_id: IntegrationId, identity_hash: str
    ) -> AwsAlarmCurrentState | None:
        record = self._session.scalar(
            select(AwsAlarmStateRecord).where(
                AwsAlarmStateRecord.integration_id == UUID(str(integration_id)),
                AwsAlarmStateRecord.alarm_identity_hash == identity_hash,
            )
        )
        return _state_from_record(record) if record else None

    def add(self, state: AwsAlarmCurrentState) -> None:
        self._session.add(_state_to_record(state))
        self._session.flush()

    def save(self, state: AwsAlarmCurrentState) -> None:
        record = _state_to_record(state)
        result = self._session.execute(
            update(AwsAlarmStateRecord)
            .where(AwsAlarmStateRecord.id == record.id)
            .values(
                alarm_name=record.alarm_name,
                latest_event_id=record.latest_event_id,
                latest_state=record.latest_state,
                latest_observed_at=record.latest_observed_at,
                updated_at=record.updated_at,
                incident_id=record.incident_id,
            )
        )
        if result.rowcount != 1:
            raise RuntimeError("Alarm state update conflicted")
        self._session.flush()


class PostgresAlertIngestionUnitOfWork:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        context: AuthorizedTenantContext,
        quota_defaults=None,
        quota_observer=None,
    ) -> None:
        if context.workspace_id is None:
            raise ValueError("Alert ingestion requires workspace scope")
        self._session_factory = session_factory
        self._context = context
        self._quota_defaults = quota_defaults
        self._quota_observer = quota_observer
        self.session: Session | None = None

    def __enter__(self) -> PostgresAlertIngestionUnitOfWork:
        self.session = self._session_factory()
        self.session.begin()
        apply_tenant_context(
            self.session,
            TenantContext(self._context.organization_id, self._context.workspace_id),
        )
        self.aws_integrations = PostgresAwsIntegrationRepository(self.session)
        self.alert_receipts = PostgresAlertReceiptRepository(self.session)
        self.alarm_states = PostgresAlarmStateRepository(self.session)
        self.incidents = PostgresHostedIncidentRepository(self.session)
        self.triage_runs = PostgresTriageRunRepository(self.session)
        self.jobs = PostgresJobRepository(self.session)
        self.dispatches = PostgresJobDispatchRepository(self.session)
        self.audit_events = PostgresAuditEventRepository(self.session)
        self.usage = PostgresUsageQuotaRepository(
            self.session, self._context, self._quota_defaults, self._quota_observer
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.session is None:
            return
        try:
            if exc_type is None:
                self.session.commit()
            else:
                self.session.rollback()
        finally:
            self.session.close()
            self.session = None


def _receipt_to_record(receipt: AlertEventReceipt) -> AlertEventReceiptRecord:
    return AlertEventReceiptRecord(
        id=UUID(str(receipt.id)),
        organization_id=UUID(str(receipt.scope.organization_id)),
        workspace_id=UUID(str(receipt.scope.workspace_id)),
        integration_id=UUID(str(receipt.integration_id)),
        event_id=receipt.event_id,
        payload_hash=receipt.payload_hash,
        alarm_identity=receipt.alarm_identity,
        alarm_identity_hash=receipt.alarm_identity_hash,
        alarm_name=receipt.alarm_name,
        account_id=receipt.account_id,
        region=receipt.region,
        alarm_state=receipt.state.value,
        previous_alarm_state=receipt.previous_state.value,
        observed_at=receipt.observed_at,
        received_at=receipt.received_at,
        status=receipt.status.value,
        incident_id=UUID(str(receipt.incident_id)) if receipt.incident_id else None,
        triage_run_id=(
            UUID(str(receipt.triage_run_id)) if receipt.triage_run_id else None
        ),
        **_actor_columns(receipt.created_by),
    )


def _receipt_from_record(record: AlertEventReceiptRecord) -> AlertEventReceipt:
    return AlertEventReceipt(
        id=AlertReceiptId(str(record.id)),
        scope=WorkspaceScope(
            OrganizationId(str(record.organization_id)),
            WorkspaceId(str(record.workspace_id)),
        ),
        integration_id=IntegrationId(str(record.integration_id)),
        event_id=record.event_id,
        payload_hash=record.payload_hash,
        alarm_identity=record.alarm_identity,
        alarm_identity_hash=record.alarm_identity_hash,
        alarm_name=record.alarm_name,
        account_id=record.account_id,
        region=record.region,
        state=CloudWatchAlarmValue(record.alarm_state),
        previous_state=CloudWatchAlarmValue(record.previous_alarm_state),
        observed_at=record.observed_at,
        received_at=record.received_at,
        status=AlertReceiptStatus(record.status),
        created_by=_actor(record.actor_kind, record.actor_id, record.actor_system_name),
        incident_id=IncidentId(str(record.incident_id)) if record.incident_id else None,
        triage_run_id=(
            TriageRunId(str(record.triage_run_id)) if record.triage_run_id else None
        ),
    )


def _state_to_record(state: AwsAlarmCurrentState) -> AwsAlarmStateRecord:
    return AwsAlarmStateRecord(
        id=UUID(str(state.id)),
        organization_id=UUID(str(state.scope.organization_id)),
        workspace_id=UUID(str(state.scope.workspace_id)),
        integration_id=UUID(str(state.integration_id)),
        alarm_identity=state.alarm_identity,
        alarm_identity_hash=state.alarm_identity_hash,
        alarm_name=state.alarm_name,
        latest_event_id=state.latest_event_id,
        latest_state=state.latest_state.value,
        latest_observed_at=state.latest_observed_at,
        updated_at=state.updated_at,
        incident_id=UUID(str(state.incident_id)) if state.incident_id else None,
    )


def _state_from_record(record: AwsAlarmStateRecord) -> AwsAlarmCurrentState:
    return AwsAlarmCurrentState(
        id=AwsAlarmStateId(str(record.id)),
        scope=WorkspaceScope(
            OrganizationId(str(record.organization_id)),
            WorkspaceId(str(record.workspace_id)),
        ),
        integration_id=IntegrationId(str(record.integration_id)),
        alarm_identity=record.alarm_identity,
        alarm_identity_hash=record.alarm_identity_hash,
        alarm_name=record.alarm_name,
        latest_event_id=record.latest_event_id,
        latest_state=CloudWatchAlarmValue(record.latest_state),
        latest_observed_at=record.latest_observed_at,
        updated_at=record.updated_at,
        incident_id=IncidentId(str(record.incident_id)) if record.incident_id else None,
    )
