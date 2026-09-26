"""Real PostgreSQL idempotency, atomic admission, counters, and RLS for V3.24."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from app.authorization.permissions import Permission
from app.application.incidents import HostedIncidentInput, HostedIncidentService
from app.authorization.service import AuthorizationService
from app.domain.common import CorrelationContext
from app.domain.identifiers import CorrelationId
from app.domain.usage import (
    QuotaExceeded,
    QuotaLimit,
    QuotaType,
    QuotaWindow,
    UsageSourceConflict,
    UsageType,
)
from app.persistence.postgres.authorization import (
    PostgresAuthorizationFactsRepository,
    PostgresTenantResourceValidator,
)
from app.persistence.postgres.engine import create_postgres_engine, create_session_factory
from app.persistence.postgres.incident_unit_of_work import PostgresHostedIncidentUnitOfWork
from app.persistence.postgres.models import (
    JobDispatchRecord,
    JobRecord,
    TriageRunRecord,
    UsageCounterRecord,
    UsageEventRecord,
)
from app.persistence.postgres.tenant import TenantContext, tenant_transaction
from app.persistence.postgres.usage import PostgresUsageUnitOfWork

from .conftest import PostgresTestDatabase
from .test_document_persistence import _setup

NOW = datetime(2026, 9, 26, 10, 30, tzinfo=UTC)


def _context(sessions, actor, organization_id, workspace_id):
    return AuthorizationService(
        PostgresAuthorizationFactsRepository(sessions),
        PostgresTenantResourceValidator(sessions),
    ).authorize(actor, organization_id, Permission.USAGE_READ, workspace_id=workspace_id)


def test_duplicate_event_increments_counter_once_and_rls_fails_closed(
    postgres_database: PostgresTestDatabase, runtime_session_factory
) -> None:
    actor, organization_id, _, workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 724
    )
    context = _context(runtime_session_factory, actor, organization_id, workspace.id)
    correlation = CorrelationContext(CorrelationId.new())
    with PostgresUsageUnitOfWork(runtime_session_factory, context) as uow:
        assert uow.usage.record(
            UsageType.DOCUMENT_BYTES_STORED,
            128,
            source="document_version",
            source_reference="version-1",
            correlation=correlation,
            actor=context.actor,
            at=NOW,
        )
        assert not uow.usage.record(
            UsageType.DOCUMENT_BYTES_STORED,
            128,
            source="document_version",
            source_reference="version-1",
            correlation=correlation,
            actor=context.actor,
            at=NOW,
        )

    with tenant_transaction(
        runtime_session_factory, TenantContext(organization_id, workspace.id)
    ) as session:
        assert session.scalar(select(func.count()).select_from(UsageEventRecord)) == 1
        assert session.scalar(
            select(UsageCounterRecord.quantity).where(
                UsageCounterRecord.usage_type == UsageType.DOCUMENT_BYTES_STORED.value,
                UsageCounterRecord.window_seconds == 0,
            )
        ) == 128

    with pytest.raises(UsageSourceConflict):
        with PostgresUsageUnitOfWork(runtime_session_factory, context) as uow:
            uow.usage.record(
                UsageType.DOCUMENT_BYTES_STORED,
                129,
                source="document_version",
                source_reference="version-1",
                correlation=correlation,
                actor=context.actor,
                at=NOW,
            )

    with runtime_session_factory.begin() as session:
        assert session.scalar(
            select(func.count()).select_from(UsageCounterRecord)
        ) == 0


def test_final_hourly_slot_is_admitted_once_under_concurrency(
    postgres_database: PostgresTestDatabase, runtime_session_factory
) -> None:
    actor, organization_id, _, workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 725
    )
    context = _context(runtime_session_factory, actor, organization_id, workspace.id)
    defaults = {
        QuotaType.TRIAGE_REQUESTS_PER_HOUR: QuotaLimit(
            QuotaType.TRIAGE_REQUESTS_PER_HOUR,
            1,
            window=QuotaWindow.UTC_HOUR,
        )
    }

    def admit(reference: str) -> str:
        try:
            with PostgresUsageUnitOfWork(
                runtime_session_factory, context, defaults
            ) as uow:
                uow.usage.decision(QuotaType.TRIAGE_REQUESTS_PER_HOUR, 1, at=NOW)
                uow.usage.record(
                    UsageType.TRIAGE_REQUESTED,
                    1,
                    source="triage_run",
                    source_reference=reference,
                    correlation=CorrelationContext(CorrelationId.new()),
                    actor=context.actor,
                    at=NOW,
                )
            return "allowed"
        except QuotaExceeded:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(admit, ("run-a", "run-b")))
    assert sorted(outcomes) == ["allowed", "rejected"]


def test_final_triage_slot_creates_one_complete_durable_request(
    postgres_database: PostgresTestDatabase, runtime_session_factory
) -> None:
    actor, organization_id, _, workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 727
    )
    engine = create_postgres_engine(
        postgres_database.runtime_engine.url.render_as_string(hide_password=False),
        pool_size=4,
        max_overflow=0,
    )
    sessions = create_session_factory(engine)
    try:
        authorization = AuthorizationService(
            PostgresAuthorizationFactsRepository(sessions),
            PostgresTenantResourceValidator(sessions),
        )
        defaults = {
            QuotaType.TRIAGE_REQUESTS_PER_HOUR: QuotaLimit(
                QuotaType.TRIAGE_REQUESTS_PER_HOUR,
                10,
                window=QuotaWindow.UTC_HOUR,
            ),
            QuotaType.CONCURRENT_TRIAGE_RUNS: QuotaLimit(
                QuotaType.CONCURRENT_TRIAGE_RUNS,
                1,
                window=QuotaWindow.CONCURRENT,
            ),
        }
        factory = lambda context: PostgresHostedIncidentUnitOfWork(  # noqa: E731
            sessions, context, defaults
        )
        service = HostedIncidentService(
            authorization, factory, clock=lambda: NOW, enforce_quotas=True
        )
        incident = service.create_incident(
            actor,
            organization_id,
            workspace.id,
            HostedIncidentInput(
                title="Final slot race",
                description="Only one durable triage request may be admitted",
                service_name="checkout-api",
                environment="production",
                source_provider="manual",
                source_type="operator",
                observed_at=NOW,
            ),
        )

        def request(key: str) -> str:
            try:
                service.request_triage(
                    actor,
                    organization_id,
                    workspace.id,
                    incident.id,
                    idempotency_key=key,
                )
                return "allowed"
            except QuotaExceeded:
                return "rejected"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = tuple(executor.map(request, ("triage-a", "triage-b")))
        assert sorted(outcomes) == ["allowed", "rejected"]

        with tenant_transaction(
            sessions, TenantContext(organization_id, workspace.id)
        ) as session:
            assert session.scalar(select(func.count()).select_from(TriageRunRecord)) == 1
            assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
            assert session.scalar(select(func.count()).select_from(JobDispatchRecord)) == 1
            assert session.scalar(
                select(func.count()).select_from(UsageEventRecord).where(
                    UsageEventRecord.category == UsageType.TRIAGE_REQUESTED.value
                )
            ) == 1
    finally:
        engine.dispose()


def test_quota_resolution_prefers_workspace_then_organization_then_default(
    postgres_database: PostgresTestDatabase, runtime_session_factory
) -> None:
    actor, organization_id, _, workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 726
    )
    context = _context(runtime_session_factory, actor, organization_id, workspace.id)
    insert_policy = text(
        """
        INSERT INTO quota_policies (
            id, organization_id, workspace_id, quota_type, hard_limit,
            warning_percent, window_kind, policy_version, created_at, updated_at,
            actor_kind, actor_id, actor_system_name
        ) VALUES (
            :id, :organization_id, :workspace_id, :quota_type, :hard_limit,
            80, 'utc_hour', :policy_version, :now, :now,
            'system', NULL, 'quota-test'
        )
        """
    )
    with postgres_database.migration_engine.begin() as connection:
        connection.execute(
            insert_policy,
            {
                "id": uuid4(),
                "organization_id": str(organization_id),
                "workspace_id": None,
                "quota_type": QuotaType.TRIAGE_REQUESTS_PER_HOUR.value,
                "hard_limit": 50,
                "policy_version": 2,
                "now": NOW,
            },
        )
        connection.execute(
            insert_policy,
            {
                "id": uuid4(),
                "organization_id": str(organization_id),
                "workspace_id": str(workspace.id),
                "quota_type": QuotaType.TRIAGE_REQUESTS_PER_HOUR.value,
                "hard_limit": 25,
                "policy_version": 3,
                "now": NOW,
            },
        )

    defaults = {
        QuotaType.TRIAGE_REQUESTS_PER_HOUR: QuotaLimit(
            QuotaType.TRIAGE_REQUESTS_PER_HOUR,
            100,
            window=QuotaWindow.UTC_HOUR,
        )
    }
    with PostgresUsageUnitOfWork(runtime_session_factory, context, defaults) as uow:
        resolved = uow.usage.limit(QuotaType.TRIAGE_REQUESTS_PER_HOUR)
        assert (resolved.hard_limit, resolved.policy_version) == (25, 3)

    with postgres_database.migration_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM quota_policies WHERE workspace_id = :workspace_id"),
            {"workspace_id": str(workspace.id)},
        )
    with PostgresUsageUnitOfWork(runtime_session_factory, context, defaults) as uow:
        resolved = uow.usage.limit(QuotaType.TRIAGE_REQUESTS_PER_HOUR)
        assert (resolved.hard_limit, resolved.policy_version) == (50, 2)

    with postgres_database.migration_engine.begin() as connection:
        connection.execute(text("DELETE FROM quota_policies"))
    with PostgresUsageUnitOfWork(runtime_session_factory, context, defaults) as uow:
        resolved = uow.usage.limit(QuotaType.TRIAGE_REQUESTS_PER_HOUR)
        assert (resolved.hard_limit, resolved.policy_version) == (100, 1)
