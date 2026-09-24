"""Real PostgreSQL hosted workspace lifecycle and RLS tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.application.workspaces import (
    HostedWorkspaceService,
    WorkspaceConflict,
    WorkspaceVersionConflict,
)
from app.auth.context import ActorContext, AuthenticationMethod
from app.authorization.permissions import Permission
from app.authorization.service import AuthorizationDenied, AuthorizationService
from app.domain.common import ActorKind, ActorReference
from app.domain.identifiers import MembershipId, OrganizationId, UserId
from app.domain.tenancy import (
    MembershipRole,
    MembershipState,
    Organization,
    OrganizationMembership,
    User,
    WorkspaceState,
)
from app.persistence.postgres.authorization import (
    PostgresAuthorizationFactsRepository,
    PostgresTenantResourceValidator,
)
from app.persistence.postgres.mappers import (
    membership_to_record,
    organization_to_record,
    user_to_record,
)
from app.persistence.postgres.models import (
    AuditEventRecord,
    OrganizationMembershipRecord,
    WorkspaceConfigurationRecord,
    WorkspaceRecord,
)
from app.persistence.postgres.tenant import TenantContext, tenant_transaction
from app.persistence.postgres.workspace_unit_of_work import PostgresWorkspaceUnitOfWork

from .conftest import PostgresTestDatabase

NOW = datetime(2026, 9, 24, 15, 0, tzinfo=UTC)


def _id(identifier_type, suffix: int):
    return identifier_type(f"00000000-0000-4000-8000-{suffix:012d}")


def _actor(user_id: UserId) -> ActorContext:
    return ActorContext(
        actor=ActorReference(ActorKind.HUMAN, actor_id=user_id),
        authentication_method=AuthenticationMethod.OIDC,
        issuer="https://issuer.example",
        external_subject=f"subject-{user_id}",
    )


def _seed_owner(database: PostgresTestDatabase, suffix: int = 1):
    user_id = _id(UserId, suffix)
    organization_id = _id(OrganizationId, suffix + 100)
    actor = ActorReference(ActorKind.HUMAN, actor_id=user_id)
    user = User(
        id=user_id,
        email=f"owner-{suffix}@example.com",
        display_name=f"Owner {suffix}",
        identity_provider="https://issuer.example",
        provider_subject=f"subject-{user_id}",
        created_at=NOW,
    )
    organization = Organization(
        id=organization_id,
        name=f"Organization {suffix}",
        slug=f"organization-{suffix}",
        created_by=actor,
        created_at=NOW,
        updated_at=NOW,
    )
    membership = OrganizationMembership(
        id=_id(MembershipId, suffix + 200),
        organization_id=organization_id,
        user_id=user_id,
        role=MembershipRole.OWNER,
        state=MembershipState.ACTIVE,
        created_by=actor,
        created_at=NOW,
        updated_at=NOW,
    )
    with Session(database.migration_engine) as session, session.begin():
        session.add(user_to_record(user))
        session.add(organization_to_record(organization))
        session.flush()
        session.add(membership_to_record(membership))
    return user_id, organization_id, membership.id


def _service(runtime_session_factory) -> HostedWorkspaceService:
    authorization = _authorization(runtime_session_factory)
    return HostedWorkspaceService(
        authorization,
        lambda context: PostgresWorkspaceUnitOfWork(
            runtime_session_factory, context
        ),
        clock=lambda: NOW,
    )


def _authorization(runtime_session_factory) -> AuthorizationService:
    return AuthorizationService(
        PostgresAuthorizationFactsRepository(runtime_session_factory),
        PostgresTenantResourceValidator(runtime_session_factory),
    )


def test_workspace_lifecycle_configuration_and_audit_are_durable(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    user_id, organization_id, _membership_id = _seed_owner(postgres_database)
    service = _service(runtime_session_factory)
    actor = _actor(user_id)

    workspace = service.create(
        actor,
        organization_id,
        name="Production API",
        slug="production-api",
        description="Primary service",
    )
    with pytest.raises(WorkspaceConflict, match="slug"):
        service.create(
            actor,
            organization_id,
            name="Duplicate",
            slug="production-api",
        )
    assert service.get(actor, organization_id, workspace.id) == workspace
    assert service.list_visible(actor, organization_id) == (workspace,)
    configuration = service.get_configuration(actor, organization_id, workspace.id)
    assert configuration.schema_version == 1
    assert configuration.version == 1

    updated = service.update_metadata(
        actor,
        organization_id,
        workspace.id,
        expected_version=workspace.version,
        name="Production Gateway",
    )
    configured = service.update_configuration(
        actor,
        organization_id,
        workspace.id,
        {"rag_top_k": 16, "llm_temperature": 0.5},
        expected_version=configuration.version,
    )
    assert updated.version == 2
    assert configured.version == 2
    assert configured.updated_by == actor.actor

    with pytest.raises(WorkspaceVersionConflict):
        service.update_metadata(
            actor,
            organization_id,
            workspace.id,
            expected_version=1,
            name="Stale",
        )

    archived = service.archive(
        actor,
        organization_id,
        workspace.id,
        expected_version=updated.version,
    )
    assert archived.state is WorkspaceState.ARCHIVED
    with pytest.raises(AuthorizationDenied):
        service.get(actor, organization_id, workspace.id)

    with Session(postgres_database.migration_engine) as session:
        events = session.scalars(
            select(AuditEventRecord).order_by(AuditEventRecord.occurred_at)
        ).all()
        assert len(events) == 4
        assert {event.event_type for event in events} == {
            "workspace.created",
            "workspace.metadata_updated",
            "workspace.configuration_updated",
            "workspace.archived",
        }
        assert all(event.actor_id == UUID(str(user_id)) for event in events)
        assert all(event.workspace_id == UUID(str(workspace.id)) for event in events)


def test_workspace_configuration_rls_fails_closed_and_isolates_scope(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    first_user, first_org, _ = _seed_owner(postgres_database, 10)
    second_user, second_org, _ = _seed_owner(postgres_database, 20)
    service = _service(runtime_session_factory)
    first = service.create(
        _actor(first_user), first_org, name="First", slug="first"
    )
    second = service.create(
        _actor(second_user), second_org, name="Second", slug="second"
    )

    with runtime_session_factory.begin() as session:
        assert session.scalar(
            select(func.count()).select_from(WorkspaceConfigurationRecord)
        ) == 0

    with tenant_transaction(
        runtime_session_factory, TenantContext(first_org, first.id)
    ) as session:
        assert session.scalars(select(WorkspaceConfigurationRecord.workspace_id)).all() == [
            UUID(str(first.id))
        ]

    with pytest.raises(ProgrammingError):
        with tenant_transaction(
            runtime_session_factory, TenantContext(first_org, first.id)
        ) as session:
            session.add(
                WorkspaceConfigurationRecord(
                    workspace_id=UUID(str(second.id)),
                    organization_id=UUID(str(second_org)),
                    schema_version=1,
                    version=1,
                    rag_top_k=8,
                    llm_temperature=0.2,
                    updated_by_kind=ActorKind.HUMAN.value,
                    updated_by_id=UUID(str(first_user)),
                    updated_by_system_name=None,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            session.flush()


def test_role_revocation_is_observed_before_workspace_service_work(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    user_id, organization_id, membership_id = _seed_owner(postgres_database, 30)
    service = _service(runtime_session_factory)
    workspace = service.create(
        _actor(user_id), organization_id, name="Mutable", slug="mutable"
    )
    with Session(postgres_database.migration_engine) as session, session.begin():
        membership = session.get(
            OrganizationMembershipRecord, UUID(str(membership_id))
        )
        membership.state = MembershipState.SUSPENDED.value

    with pytest.raises(AuthorizationDenied):
        service.update_metadata(
            _actor(user_id),
            organization_id,
            workspace.id,
            expected_version=workspace.version,
            name="Denied",
        )

    with Session(postgres_database.migration_engine) as session:
        record = session.get(WorkspaceRecord, UUID(str(workspace.id)))
        assert record.name == "Mutable"


def test_repository_compare_and_swap_closes_concurrent_update_window(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    user_id, organization_id, _membership_id = _seed_owner(postgres_database, 40)
    actor = _actor(user_id)
    service = _service(runtime_session_factory)
    workspace = service.create(
        actor, organization_id, name="Concurrent", slug="concurrent"
    )
    context = _authorization(runtime_session_factory).authorize(
        actor,
        organization_id,
        Permission.WORKSPACE_UPDATE,
        workspace_id=workspace.id,
    )

    with PostgresWorkspaceUnitOfWork(runtime_session_factory, context) as uow:
        stale = uow.workspaces.get(workspace.id)
    service.update_metadata(
        actor,
        organization_id,
        workspace.id,
        expected_version=1,
        name="Client B",
    )
    assert stale is not None
    with pytest.raises(WorkspaceVersionConflict):
        with PostgresWorkspaceUnitOfWork(runtime_session_factory, context) as uow:
            uow.workspaces.save(
                stale.update_metadata(name="Client A", at=NOW),
                expected_version=1,
            )
