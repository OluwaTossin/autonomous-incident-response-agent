"""Real PostgreSQL atomicity, concurrency, and RLS tests for alert ingestion."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.application.alert_ingestion import (
    AlertIngestionConflict,
    AlertIngestionOutcome,
    HostedAlertIngestionService,
)
from app.authorization.permissions import Permission
from app.authorization.service import (
    AuthorizationDenied,
    AuthorizationService,
    SystemAuthorizationGrant,
)
from app.auth.context import trusted_system_actor
from app.domain.alert_ingestion import CloudWatchAlarmEvent, CloudWatchAlarmValue
from app.persistence.postgres.alert_ingestion import PostgresAlertIngestionUnitOfWork
from app.persistence.postgres.authorization import (
    PostgresAuthorizationFactsRepository,
    PostgresTenantResourceValidator,
)
from app.persistence.postgres.models import (
    AlertEventReceiptRecord,
    AuditEventRecord,
    AwsAlarmStateRecord,
    IncidentRecord,
    JobDispatchRecord,
    JobRecord,
    TriageRunRecord,
)
from app.persistence.postgres.tenant import TenantContext, tenant_transaction

from .conftest import PostgresTestDatabase
from .test_aws_integration_persistence import _service as aws_integration_service
from .test_document_persistence import NOW, _setup
from .test_workspace_persistence import _service as workspace_service


def _machine():
    return trusted_system_actor(
        system_name="alert-ingress",
        workload_issuer="https://sts.example",
        workload_subject="role/alert-ingress",
    )


def _ready_integration(runtime_session_factory, actor, organization_id, workspace_id):
    service = aws_integration_service(runtime_session_factory)
    created = service.create(
        actor,
        organization_id,
        workspace_id,
        display_name="Production AWS",
        aws_account_id="123456789012",
        enabled_regions=("eu-west-2",),
    )
    configured = service.update(
        actor,
        organization_id,
        workspace_id,
        created.id,
        expected_version=created.version,
        role_arn="arn:aws:iam::123456789012:role/aira-read",
    )
    return service.verify(
        actor,
        organization_id,
        workspace_id,
        configured.id,
        expected_version=configured.version,
    )


def _service(runtime_session_factory, organization_id, workspace_id, uow_factory=None):
    authorization = AuthorizationService(
        PostgresAuthorizationFactsRepository(runtime_session_factory),
        PostgresTenantResourceValidator(runtime_session_factory),
        system_grants=(
            SystemAuthorizationGrant(
                "alert-ingress",
                "https://sts.example",
                "role/alert-ingress",
                organization_id,
                frozenset(
                    {
                        Permission.INTEGRATION_READ,
                        Permission.INCIDENT_CREATE,
                        Permission.TRIAGE_RUN,
                        Permission.JOB_CREATE,
                    }
                ),
                frozenset({workspace_id}),
            ),
        ),
    )
    return HostedAlertIngestionService(
        authorization,
        uow_factory
        or (
            lambda context: PostgresAlertIngestionUnitOfWork(
                runtime_session_factory, context
            )
        ),
        clock=lambda: NOW,
        monotonic=lambda: 1.0,
    )


def _event(event_id="11111111-1111-4111-8111-111111111111", **changes):
    values = {
        "schema_version": 1,
        "event_id": event_id,
        "account_id": "123456789012",
        "region": "eu-west-2",
        "observed_at": NOW - timedelta(minutes=1),
        "alarm_name": "payments-latency",
        "alarm_arn": "arn:aws:cloudwatch:eu-west-2:123456789012:alarm:payments-latency",
        "state": CloudWatchAlarmValue.ALARM,
        "previous_state": CloudWatchAlarmValue.OK,
        "reason": "Threshold crossed",
        "resources": (
            "arn:aws:cloudwatch:eu-west-2:123456789012:alarm:payments-latency",
        ),
    }
    values.update(changes)
    return CloudWatchAlarmEvent(**values)


def test_alert_ingestion_is_atomic_durable_and_idempotent(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    actor, organization_id, _, workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 270
    )
    integration = _ready_integration(
        runtime_session_factory, actor, organization_id, workspace.id
    )
    service = _service(runtime_session_factory, organization_id, workspace.id)

    first = service.ingest(
        _machine(), organization_id, workspace.id, integration.id, _event()
    )
    duplicate = service.ingest(
        _machine(), organization_id, workspace.id, integration.id, _event()
    )
    assert first.outcome is AlertIngestionOutcome.ACCEPTED
    assert duplicate.outcome is AlertIngestionOutcome.DUPLICATE
    assert duplicate.incident_id == first.incident_id

    with tenant_transaction(
        runtime_session_factory, TenantContext(organization_id, workspace.id)
    ) as session:
        assert session.scalar(select(func.count()).select_from(AlertEventReceiptRecord)) == 1
        assert session.scalar(select(func.count()).select_from(AwsAlarmStateRecord)) == 1
        assert session.scalar(select(func.count()).select_from(IncidentRecord)) == 1
        assert session.scalar(select(func.count()).select_from(TriageRunRecord)) == 1
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        assert session.scalar(select(func.count()).select_from(JobDispatchRecord)) == 1
        events = set(session.scalars(select(AuditEventRecord.event_type)).all())
        assert {
            "alarm_event.accepted",
            "alarm_event.duplicate",
            "incident.created",
            "triage.requested",
        } <= events

    with pytest.raises(AlertIngestionConflict, match="different content"):
        service.ingest(
            _machine(),
            organization_id,
            workspace.id,
            integration.id,
            _event(reason="Conflicting delivery"),
        )


def test_concurrent_duplicate_delivery_creates_one_workflow(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    actor, organization_id, _, workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 271
    )
    integration = _ready_integration(
        runtime_session_factory, actor, organization_id, workspace.id
    )
    service = _service(runtime_session_factory, organization_id, workspace.id)

    def ingest():
        return service.ingest(
            _machine(), organization_id, workspace.id, integration.id, _event()
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(ingest), executor.submit(ingest)]
        outcomes = {future.result().outcome for future in futures}
    assert outcomes == {AlertIngestionOutcome.ACCEPTED, AlertIngestionOutcome.DUPLICATE}
    with tenant_transaction(
        runtime_session_factory, TenantContext(organization_id, workspace.id)
    ) as session:
        assert session.scalar(select(func.count()).select_from(AlertEventReceiptRecord)) == 1
        assert session.scalar(select(func.count()).select_from(IncidentRecord)) == 1
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1


def test_ingestion_failure_rolls_back_receipt_and_workflow(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    actor, organization_id, _, workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 272
    )
    integration = _ready_integration(
        runtime_session_factory, actor, organization_id, workspace.id
    )

    class FailingDispatches:
        def add(self, job, *, at):
            raise RuntimeError("dispatch failed")

    class FailingUow(PostgresAlertIngestionUnitOfWork):
        def __enter__(self):
            value = super().__enter__()
            self.dispatches = FailingDispatches()
            return value

    service = _service(
        runtime_session_factory,
        organization_id,
        workspace.id,
        lambda context: FailingUow(runtime_session_factory, context),
    )
    with pytest.raises(RuntimeError, match="dispatch failed"):
        service.ingest(
            _machine(), organization_id, workspace.id, integration.id, _event()
        )
    with tenant_transaction(
        runtime_session_factory, TenantContext(organization_id, workspace.id)
    ) as session:
        assert session.scalar(select(func.count()).select_from(AlertEventReceiptRecord)) == 0
        assert session.scalar(select(func.count()).select_from(IncidentRecord)) == 0
        assert session.scalar(select(func.count()).select_from(TriageRunRecord)) == 0
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 0


def test_alert_receipts_and_state_are_forced_rls_scoped(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    actor, organization_id, _, workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 273
    )
    _, other_organization, _, other_workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 274
    )
    integration = _ready_integration(
        runtime_session_factory, actor, organization_id, workspace.id
    )
    service = _service(runtime_session_factory, organization_id, workspace.id)
    same_org_workspace = workspace_service(runtime_session_factory).create(
        actor,
        organization_id,
        name="Other workspace",
        slug="other-workspace",
    )
    result = service.ingest(
        _machine(), organization_id, workspace.id, integration.id, _event()
    )

    with pytest.raises(AuthorizationDenied):
        service.ingest(
            _machine(),
            organization_id,
            same_org_workspace.id,
            integration.id,
            _event(event_id="22222222-2222-4222-8222-222222222222"),
        )

    with runtime_session_factory.begin() as session:
        assert session.scalar(select(func.count()).select_from(AlertEventReceiptRecord)) == 0
        assert session.scalar(select(func.count()).select_from(AwsAlarmStateRecord)) == 0
    with tenant_transaction(
        runtime_session_factory,
        TenantContext(other_organization, other_workspace.id),
    ) as session:
        assert session.get(AlertEventReceiptRecord, UUID(str(result.receipt_id))) is None
        assert session.scalar(select(func.count()).select_from(AlertEventReceiptRecord)) == 0
        assert session.scalar(select(func.count()).select_from(AwsAlarmStateRecord)) == 0
    with tenant_transaction(
        runtime_session_factory,
        TenantContext(organization_id, same_org_workspace.id),
    ) as session:
        assert session.get(AlertEventReceiptRecord, UUID(str(result.receipt_id))) is None
        assert session.scalar(select(func.count()).select_from(AlertEventReceiptRecord)) == 0
        assert session.scalar(select(func.count()).select_from(AwsAlarmStateRecord)) == 0
