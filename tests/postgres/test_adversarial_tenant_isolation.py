"""Real PostgreSQL attacks against forced RLS and pooled tenant context."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.domain.common import ActorKind, ActorReference, CorrelationContext, WorkspaceScope
from app.domain.identifiers import CorrelationId, DocumentId, IncidentId, OrganizationId, UserId, WorkspaceId
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
from app.persistence.postgres.models import Base, IncidentRecord
from app.persistence.postgres.tenant import TenantContext, tenant_transaction

from .conftest import PostgresTestDatabase

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


def _id(identifier_type, suffix: int):
    return identifier_type(f"00000000-0000-4000-8000-{suffix:012d}")


def _actor(suffix: int = 900) -> ActorReference:
    return ActorReference(ActorKind.HUMAN, actor_id=_id(UserId, suffix))


def _tenant(suffix: int) -> tuple[Organization, Workspace, Incident]:
    organization = Organization(
        id=_id(OrganizationId, suffix),
        name=f"Adversarial organization {suffix}",
        slug=f"adversarial-organization-{suffix}",
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
        correlation=CorrelationContext(_id(CorrelationId, suffix + 300), incident_id=incident_id),
    )
    return organization, workspace, incident


def _seed(database: PostgresTestDatabase):
    tenants = (_tenant(701), _tenant(702))
    with Session(database.migration_engine) as session, session.begin():
        session.add_all(organization_to_record(item[0]) for item in tenants)
        session.flush()
        session.add_all(workspace_to_record(item[1]) for item in tenants)
        session.flush()
        session.add_all(incident_to_record(item[2]) for item in tenants)
    return tenants


def test_rls_inventory_has_force_policies_checks_and_non_owner_runtime_role(
    postgres_database: PostgresTestDatabase,
) -> None:
    tenant_tables = {
        table.name
        for table in Base.metadata.sorted_tables
        if table.name == "organizations" or "organization_id" in table.columns
    }
    with postgres_database.migration_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT c.relname AS table_name, c.relrowsecurity AS enabled, "
                "c.relforcerowsecurity AS forced, owner.rolname AS owner, "
                "count(p.policyname) AS policy_count, "
                "bool_or(p.qual IS NOT NULL) AS has_using, "
                "bool_or(p.with_check IS NOT NULL) AS has_check "
                "FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "JOIN pg_roles owner ON owner.oid = c.relowner "
                "LEFT JOIN pg_policies p ON p.schemaname = n.nspname "
                "AND p.tablename = c.relname "
                "WHERE n.nspname = 'public' AND c.relkind = 'r' "
                "GROUP BY c.relname, c.relrowsecurity, c.relforcerowsecurity, owner.rolname"
            )
        ).mappings()
        inventory = {row["table_name"]: row for row in rows}
    with postgres_database.runtime_engine.connect() as connection:
        runtime_role = connection.scalar(text("SELECT current_user"))
        bypass = connection.scalar(
            text("SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user")
        )

    assert tenant_tables <= inventory.keys()
    assert bypass is False
    for table_name in tenant_tables:
        row = inventory[table_name]
        assert row["enabled"] is True, table_name
        assert row["forced"] is True, table_name
        assert row["policy_count"] >= 1, table_name
        assert row["has_using"] is True, table_name
        assert row["has_check"] is True, table_name
        assert row["owner"] != runtime_role, table_name


def test_pooled_context_is_cleared_after_commit_and_rollback(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    first, second = _seed(postgres_database)
    first_context = TenantContext(first[0].id, first[1].id)
    second_context = TenantContext(second[0].id, second[1].id)

    with tenant_transaction(runtime_session_factory, first_context) as session:
        backend_pid = session.scalar(text("SELECT pg_backend_pid()"))
        assert session.scalars(select(IncidentRecord.id)).all() == [UUID(str(first[2].id))]

    with pytest.raises(RuntimeError, match="force rollback"):
        with tenant_transaction(runtime_session_factory, second_context) as session:
            assert session.scalar(text("SELECT pg_backend_pid()")) == backend_pid
            assert session.scalars(select(IncidentRecord.id)).all() == [UUID(str(second[2].id))]
            raise RuntimeError("force rollback")

    with runtime_session_factory.begin() as session:
        assert session.scalar(text("SELECT pg_backend_pid()")) == backend_pid
        assert session.scalar(select(func.count()).select_from(IncidentRecord)) == 0
        assert session.scalar(text("SELECT current_setting('app.organization_id', true)")) == ""
        assert session.scalar(text("SELECT current_setting('app.workspace_id', true)")) == ""

    with tenant_transaction(runtime_session_factory, second_context) as session:
        assert session.scalar(text("SELECT pg_backend_pid()")) == backend_pid
        assert session.scalars(select(IncidentRecord.id)).all() == [UUID(str(second[2].id))]


def test_runtime_raw_rls_bypass_and_foreign_mutations_fail_closed(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    first, second = _seed(postgres_database)
    first_context = TenantContext(first[0].id, first[1].id)

    with pytest.raises(DBAPIError):
        with runtime_session_factory.begin() as session:
            session.execute(text("SET LOCAL row_security = off"))
            session.scalar(select(func.count()).select_from(IncidentRecord))

    with tenant_transaction(runtime_session_factory, first_context) as session:
        assert session.execute(
            update(IncidentRecord)
            .where(IncidentRecord.id == UUID(str(second[2].id)))
            .values(state="resolved")
        ).rowcount == 0
        assert session.execute(
            delete(IncidentRecord).where(IncidentRecord.id == UUID(str(second[2].id)))
        ).rowcount == 0

    with pytest.raises(DBAPIError):
        with tenant_transaction(runtime_session_factory, first_context) as session:
            session.execute(
                update(IncidentRecord)
                .where(IncidentRecord.id == UUID(str(first[2].id)))
                .values(
                    organization_id=UUID(str(second[0].id)),
                    workspace_id=UUID(str(second[1].id)),
                )
            )

    with tenant_transaction(runtime_session_factory, first_context) as session:
        assert session.scalars(select(IncidentRecord.id)).all() == [UUID(str(first[2].id))]


def test_composite_scope_and_with_check_reject_cross_tenant_insert(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    first, second = _seed(postgres_database)
    invalid = Document(
        id=_id(DocumentId, 999),
        scope=WorkspaceScope(first[0].id, second[1].id),
        name="cross-tenant.md",
        category=DocumentCategory.RUNBOOK,
        state=DocumentState.PENDING_UPLOAD,
        created_by=_actor(),
        created_at=NOW,
        updated_at=NOW,
    )
    with pytest.raises(IntegrityError):
        with Session(postgres_database.migration_engine) as session, session.begin():
            session.add(document_to_record(invalid))

    foreign = replace(invalid, scope=second[1].scope)
    with pytest.raises(DBAPIError):
        with tenant_transaction(
            runtime_session_factory,
            TenantContext(first[0].id, first[1].id),
        ) as session:
            session.add(document_to_record(foreign))
