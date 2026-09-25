"""PostgreSQL migration, constraint, RLS, repository, and transaction evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from app.domain.common import (
    ActorKind,
    ActorReference,
    CorrelationContext,
    OrganizationScope,
    WorkspaceScope,
)
from app.domain.events import AuditEvent
from app.domain.identifiers import (
    AuditEventId,
    CorrelationId,
    DocumentId,
    IncidentId,
    OrganizationId,
    UserId,
    WorkspaceId,
)
from app.domain.incidents import Incident, IncidentSource, IncidentState
from app.domain.knowledge import Document, DocumentCategory, DocumentState
from app.domain.tenancy import Organization, Workspace
from app.models.incident import IncidentPayload
from app.persistence.postgres.mappers import (
    document_to_record,
    incident_to_record,
    organization_to_record,
    workspace_to_record,
)
from app.persistence.postgres.models import (
    IncidentRecord,
    OrganizationRecord,
)
from app.persistence.postgres.tenant import TenantContext, tenant_transaction
from app.persistence.postgres.unit_of_work import PostgresUnitOfWork

from .conftest import PostgresTestDatabase

NOW = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)


def _id(identifier_type, suffix: int):
    return identifier_type(f"00000000-0000-4000-8000-{suffix:012d}")


def _actor(suffix: int = 900) -> ActorReference:
    return ActorReference(ActorKind.HUMAN, actor_id=_id(UserId, suffix))


def _tenant(suffix: int) -> tuple[Organization, Workspace, Incident]:
    organization = Organization(
        id=_id(OrganizationId, suffix),
        name=f"Organization {suffix}",
        slug=f"organization-{suffix}",
        created_by=_actor(),
        created_at=NOW,
        updated_at=NOW,
    )
    workspace = Workspace(
        id=_id(WorkspaceId, suffix + 100),
        organization_id=organization.id,
        name=f"Workspace {suffix}",
        slug=f"workspace-{suffix}",
        created_by=_actor(),
        created_at=NOW,
        updated_at=NOW,
    )
    incident_id = _id(IncidentId, suffix + 200)
    incident = Incident(
        id=incident_id,
        scope=workspace.scope,
        payload=IncidentPayload(alert_title=f"Alert {suffix}", service_name="api"),
        source=IncidentSource("test", "fixture", NOW, external_id=f"event-{suffix}"),
        state=IncidentState.OPEN,
        created_by=_actor(),
        created_at=NOW,
        updated_at=NOW,
        correlation=CorrelationContext(
            _id(CorrelationId, suffix + 300),
            incident_id=incident_id,
        ),
    )
    return organization, workspace, incident


def _seed_tenants(database: PostgresTestDatabase, *suffixes: int):
    tenants = [_tenant(suffix) for suffix in suffixes]
    with Session(database.migration_engine) as session, session.begin():
        for organization, _workspace, _incident in tenants:
            session.add(organization_to_record(organization))
        session.flush()
        for _organization, workspace, _incident in tenants:
            session.add(workspace_to_record(workspace))
        session.flush()
        for _organization, _workspace, incident in tenants:
            session.add(incident_to_record(incident))
    return tenants


def _seed_same_organization_workspaces(
    database: PostgresTestDatabase,
) -> tuple[Organization, tuple[Workspace, Incident], tuple[Workspace, Incident]]:
    organization, first_workspace, first_incident = _tenant(80)
    _other_organization, candidate_workspace, candidate_incident = _tenant(81)
    second_workspace = replace(candidate_workspace, organization_id=organization.id)
    second_incident = replace(candidate_incident, scope=second_workspace.scope)

    with Session(database.migration_engine) as session, session.begin():
        session.add(organization_to_record(organization))
        session.flush()
        session.add_all(
            [
                workspace_to_record(first_workspace),
                workspace_to_record(second_workspace),
            ]
        )
        session.flush()
        session.add_all(
            [incident_to_record(first_incident), incident_to_record(second_incident)]
        )

    return (
        organization,
        (first_workspace, first_incident),
        (second_workspace, second_incident),
    )


def test_fresh_migration_contains_expected_schema(
    postgres_database: PostgresTestDatabase,
) -> None:
    with postgres_database.migration_engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        tables = set(
            connection.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
                )
            ).scalars()
        )

    assert revision == "3a6f8c1d9e42"
    assert {
        "users",
        "organizations",
        "organization_memberships",
        "workspaces",
        "incidents",
        "triage_runs",
        "evidence",
        "feedback",
        "documents",
        "document_versions",
        "knowledge_index_versions",
        "integrations",
        "jobs",
        "action_proposals",
        "approvals",
        "usage_events",
        "audit_events",
        "service_accounts",
        "service_account_credentials",
        "membership_workspace_grants",
        "service_account_authorization_grants",
        "service_account_workspace_grants",
        "workspace_configurations",
        "oauth_login_transactions",
        "browser_sessions",
        "aws_integrations",
        "alert_event_receipts",
        "aws_alarm_states",
    } <= tables


def test_composite_foreign_key_rejects_cross_organization_workspace(
    postgres_database: PostgresTestDatabase,
) -> None:
    first, second = _seed_tenants(postgres_database, 1, 2)
    document = Document(
        id=_id(DocumentId, 700),
        scope=WorkspaceScope(first[0].id, second[1].id),
        name="invalid.md",
        category=DocumentCategory.RUNBOOK,
        state=DocumentState.PENDING_UPLOAD,
        created_by=_actor(),
        created_at=NOW,
        updated_at=NOW,
    )

    with pytest.raises(IntegrityError):
        with Session(postgres_database.migration_engine) as session, session.begin():
            session.add(document_to_record(document))


def test_unique_workspace_slug_is_enforced(
    postgres_database: PostgresTestDatabase,
) -> None:
    organization, workspace, _incident = _seed_tenants(postgres_database, 10)[0]
    duplicate = Workspace(
        id=_id(WorkspaceId, 999),
        organization_id=organization.id,
        name="Duplicate",
        slug=workspace.slug,
        created_by=_actor(),
        created_at=NOW,
        updated_at=NOW,
    )

    with pytest.raises(IntegrityError):
        with Session(postgres_database.migration_engine) as session, session.begin():
            session.add(workspace_to_record(duplicate))


def test_rls_missing_context_fails_closed(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    _seed_tenants(postgres_database, 20)

    with runtime_session_factory.begin() as session:
        assert session.scalar(select(func.count()).select_from(OrganizationRecord)) == 0
        assert session.scalar(select(func.count()).select_from(IncidentRecord)) == 0

    organization, _workspace, _incident = _tenant(21)
    with pytest.raises(ProgrammingError):
        with runtime_session_factory.begin() as session:
            session.add(organization_to_record(organization))


def test_rls_isolates_organizations_and_workspaces(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    first, second = _seed_tenants(postgres_database, 30, 31)
    first_context = TenantContext(first[0].id, first[1].id)
    second_context = TenantContext(second[0].id, second[1].id)

    with tenant_transaction(runtime_session_factory, first_context) as session:
        assert session.scalars(select(OrganizationRecord.id)).all() == [
            UUID(str(first[0].id))
        ]
        assert session.scalars(select(IncidentRecord.id)).all() == [
            UUID(str(first[2].id))
        ]

    with tenant_transaction(runtime_session_factory, second_context) as session:
        assert session.scalars(select(OrganizationRecord.id)).all() == [
            UUID(str(second[0].id))
        ]
        assert session.scalars(select(IncidentRecord.id)).all() == [
            UUID(str(second[2].id))
        ]


def test_rls_isolates_workspaces_within_one_organization(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    organization, first, second = _seed_same_organization_workspaces(postgres_database)

    with tenant_transaction(
        runtime_session_factory,
        TenantContext(organization.id, first[0].id),
    ) as session:
        assert session.scalars(select(IncidentRecord.id)).all() == [
            UUID(str(first[1].id))
        ]

    with tenant_transaction(
        runtime_session_factory,
        TenantContext(organization.id, second[0].id),
    ) as session:
        assert session.scalars(select(IncidentRecord.id)).all() == [
            UUID(str(second[1].id))
        ]

    with tenant_transaction(
        runtime_session_factory,
        TenantContext(organization.id),
    ) as session:
        assert session.scalar(select(func.count()).select_from(IncidentRecord)) == 0


def test_rls_with_check_rejects_cross_workspace_insert(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    first, second = _seed_tenants(postgres_database, 40, 41)

    with pytest.raises(ProgrammingError):
        with tenant_transaction(
            runtime_session_factory,
            TenantContext(first[0].id, first[1].id),
        ) as session:
            document = Document(
                id=_id(DocumentId, 701),
                scope=second[1].scope,
                name="cross-tenant.md",
                category=DocumentCategory.RUNBOOK,
                state=DocumentState.PENDING_UPLOAD,
                created_by=_actor(),
                created_at=NOW,
                updated_at=NOW,
            )
            session.add(document_to_record(document))


def test_transaction_local_context_does_not_leak_through_pool(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    first, second = _seed_tenants(postgres_database, 50, 51)

    with tenant_transaction(
        runtime_session_factory,
        TenantContext(first[0].id, first[1].id),
    ) as session:
        first_pid = session.scalar(text("SELECT pg_backend_pid()"))
        assert session.scalars(select(IncidentRecord.id)).all() == [
            UUID(str(first[2].id))
        ]

    with runtime_session_factory.begin() as session:
        assert session.scalar(text("SELECT pg_backend_pid()")) == first_pid
        assert session.scalar(select(func.count()).select_from(IncidentRecord)) == 0
        assert (
            session.scalar(text("SELECT current_setting('app.organization_id', true)"))
            == ""
        )

    with tenant_transaction(
        runtime_session_factory,
        TenantContext(second[0].id, second[1].id),
    ) as session:
        assert session.scalar(text("SELECT pg_backend_pid()")) == first_pid
        assert session.scalars(select(IncidentRecord.id)).all() == [
            UUID(str(second[2].id))
        ]


def test_runtime_role_is_non_owner_without_rls_bypass(
    postgres_database: PostgresTestDatabase,
) -> None:
    with postgres_database.runtime_engine.connect() as connection:
        role = connection.execute(
            text(
                "SELECT rolsuper, rolcreaterole, rolcreatedb, rolbypassrls "
                "FROM pg_roles WHERE rolname = current_user"
            )
        ).one()
        owned_tables = connection.execute(
            text(
                "SELECT count(*) FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner "
                "WHERE c.relkind = 'r' AND c.relnamespace = 'public'::regnamespace "
                "AND r.rolname = current_user"
            )
        ).scalar_one()
        can_create = connection.scalar(
            text("SELECT has_schema_privilege(current_user, 'public', 'CREATE')")
        )
        can_update_migration_history = connection.scalar(
            text(
                "SELECT has_table_privilege(current_user, 'alembic_version', 'UPDATE')"
            )
        )

    assert tuple(role) == (False, False, False, False)
    assert owned_tables == 0
    assert can_create is False
    assert can_update_migration_history is False


def test_unit_of_work_persists_repositories_and_authoritative_audit(
    runtime_session_factory,
) -> None:
    organization, workspace, incident = _tenant(60)
    audit = AuditEvent(
        id=_id(AuditEventId, 800),
        organization_scope=OrganizationScope(organization.id),
        workspace_scope=workspace.scope,
        event_type="incident.created",
        target_type="incident",
        target_id=str(incident.id),
        actor=_actor(),
        occurred_at=NOW,
        correlation=incident.correlation,
        details=(("source", "test"),),
    )
    context = TenantContext(organization.id, workspace.id)

    with PostgresUnitOfWork(runtime_session_factory, context) as uow:
        uow.organizations.add(organization)
        uow.workspaces.add(workspace)
        uow.incidents.add(incident)
        uow.audit_events.add(audit)

    with PostgresUnitOfWork(runtime_session_factory, context) as uow:
        assert uow.organizations.get(organization.id) == organization
        assert uow.workspaces.get(workspace.id) == workspace
        assert uow.incidents.get(incident.id) == incident
        assert uow.audit_events.get(audit.id) == audit


def test_unit_of_work_rolls_back_on_error(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    organization, _workspace, _incident = _tenant(70)
    context = TenantContext(organization.id)

    with pytest.raises(RuntimeError, match="abort"):
        with PostgresUnitOfWork(runtime_session_factory, context) as uow:
            uow.organizations.add(organization)
            raise RuntimeError("abort")

    with postgres_database.migration_engine.connect() as connection:
        count = connection.scalar(
            select(func.count())
            .select_from(OrganizationRecord)
            .where(OrganizationRecord.id == UUID(str(organization.id)))
        )
    assert count == 0
