"""Real PostgreSQL context snapshot idempotency and RLS evidence."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.identifiers import IncidentContextItemId, IncidentContextSnapshotId
from app.domain.incident_context import (
    CollectorDiagnostic,
    CollectorStatus,
    ContextCollectionStatus,
    ContextItemType,
    IncidentContextItem,
    IncidentContextSnapshot,
)
from app.persistence.postgres.incident_context import PostgresIncidentContextRepository
from app.persistence.postgres.tenant import TenantContext, tenant_transaction

from .conftest import PostgresTestDatabase
from .test_alert_ingestion_persistence import (
    _event,
    _machine,
    _ready_integration,
    _service,
)
from .test_document_persistence import NOW, _setup


def test_context_snapshot_is_immutable_unique_and_rls_isolated(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    actor, organization_id, _, workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 280
    )
    _, other_organization_id, _, other_workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 281
    )
    integration = _ready_integration(
        runtime_session_factory, actor, organization_id, workspace.id
    )
    accepted = _service(runtime_session_factory, organization_id, workspace.id).ingest(
        _machine(), organization_id, workspace.id, integration.id, _event()
    )
    assert accepted.incident_id is not None
    assert accepted.triage_run_id is not None
    scope = workspace.scope
    snapshot_id = IncidentContextSnapshotId.new()
    item = IncidentContextItem(
        IncidentContextItemId.new(),
        snapshot_id,
        scope,
        ContextItemType.LOG,
        "/aws/lambda/payments:stream",
        NOW,
        {"message": "redacted timeout", "region": "eu-west-2"},
        0,
    )
    snapshot = IncidentContextSnapshot(
        snapshot_id,
        scope,
        accepted.incident_id,
        accepted.triage_run_id,
        integration.id,
        "aws.cloudwatch",
        "eu-west-2",
        NOW - timedelta(minutes=15),
        NOW + timedelta(minutes=2),
        NOW,
        ContextCollectionStatus.COMPLETE,
        "cloudwatch-context-v1",
        (CollectorDiagnostic("logs", CollectorStatus.SUCCEEDED),),
        (item,),
    )

    with tenant_transaction(
        runtime_session_factory, TenantContext(organization_id, workspace.id)
    ) as session:
        repository = PostgresIncidentContextRepository(session)
        repository.add(snapshot)
        loaded = repository.get_for_run(accepted.triage_run_id)
        assert loaded == snapshot

    with pytest.raises(IntegrityError):
        with tenant_transaction(
            runtime_session_factory, TenantContext(organization_id, workspace.id)
        ) as session:
            PostgresIncidentContextRepository(session).add(snapshot)

    with tenant_transaction(
        runtime_session_factory,
        TenantContext(other_organization_id, other_workspace.id),
    ) as session:
        assert (
            PostgresIncidentContextRepository(session).get_for_run(
                accepted.triage_run_id
            )
            is None
        )

    with tenant_transaction(
        runtime_session_factory, TenantContext(organization_id)
    ) as session:
        assert (
            PostgresIncidentContextRepository(session).get_for_run(
                accepted.triage_run_id
            )
            is None
        )
