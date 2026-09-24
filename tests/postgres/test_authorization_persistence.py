"""Real PostgreSQL authorization, RLS bridge, and audit tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.application.governance import OrganizationGovernanceService
from app.auth.context import ActorContext, AuthenticationMethod
from app.authorization.models import (
    MembershipWorkspaceGrant,
    ServiceAccountGrant,
    ServiceAccountWorkspaceGrant,
)
from app.authorization.permissions import Permission
from app.authorization.service import AuthorizationDenied, AuthorizationService
from app.domain.common import ActorKind, ActorReference, WorkspaceScope
from app.domain.identifiers import (
    MembershipId,
    MembershipWorkspaceGrantId,
    OrganizationId,
    ServiceAccountGrantId,
    ServiceAccountId,
    ServiceAccountWorkspaceGrantId,
    UserId,
    WorkspaceId,
)
from app.domain.identity import ServiceAccount
from app.domain.tenancy import (
    MembershipRole,
    MembershipState,
    Organization,
    OrganizationMembership,
    User,
    Workspace,
    WorkspaceAccessMode,
)
from app.persistence.postgres.authorization import (
    PostgresAuthorizationFactsRepository,
    PostgresTenantResourceValidator,
)
from app.persistence.postgres.governance_unit_of_work import (
    PostgresGovernanceUnitOfWork,
)
from app.persistence.postgres.mappers import (
    membership_to_record,
    membership_workspace_grant_to_record,
    organization_to_record,
    service_account_grant_to_record,
    service_account_to_record,
    service_account_workspace_grant_to_record,
    user_to_record,
    workspace_to_record,
)
from app.persistence.postgres.models import (
    AuditEventRecord,
    OrganizationMembershipRecord,
    ServiceAccountAuthorizationGrantRecord,
    WorkspaceRecord,
)
from app.persistence.postgres.tenant import authorized_tenant_transaction

from .conftest import PostgresTestDatabase

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def _id(identifier_type, suffix: int):
    return identifier_type(f"00000000-0000-4000-8000-{suffix:012d}")


def _human(user_id: UserId) -> ActorContext:
    return ActorContext(
        actor=ActorReference(ActorKind.HUMAN, actor_id=user_id),
        authentication_method=AuthenticationMethod.OIDC,
        issuer="https://issuer.example",
        external_subject=f"subject-{user_id}",
    )


def _service_actor(account_id: ServiceAccountId) -> ActorContext:
    return ActorContext(
        actor=ActorReference(ActorKind.SERVICE_ACCOUNT, actor_id=account_id),
        authentication_method=AuthenticationMethod.SERVICE_ACCOUNT,
        credential_id="lookup-id",
    )


def _authorization(runtime_session_factory) -> AuthorizationService:
    return AuthorizationService(
        PostgresAuthorizationFactsRepository(runtime_session_factory),
        PostgresTenantResourceValidator(runtime_session_factory),
    )


def _seed(database: PostgresTestDatabase):
    owner_id = _id(UserId, 1)
    restricted_id = _id(UserId, 2)
    target_id = _id(UserId, 3)
    organization_id = _id(OrganizationId, 10)
    other_organization_id = _id(OrganizationId, 11)
    first_workspace_id = _id(WorkspaceId, 20)
    second_workspace_id = _id(WorkspaceId, 21)
    actor = ActorReference(ActorKind.HUMAN, actor_id=owner_id)
    users = [
        User(
            id=user_id,
            email=f"user-{index}@example.com",
            display_name=f"User {index}",
            identity_provider="https://issuer.example",
            provider_subject=f"subject-{user_id}",
            created_at=NOW,
        )
        for index, user_id in enumerate((owner_id, restricted_id, target_id), 1)
    ]
    organizations = [
        Organization(
            id=organization_id,
            name="Primary",
            slug="primary",
            created_by=actor,
            created_at=NOW,
            updated_at=NOW,
        ),
        Organization(
            id=other_organization_id,
            name="Other",
            slug="other",
            created_by=actor,
            created_at=NOW,
            updated_at=NOW,
        ),
    ]
    workspaces = [
        Workspace(
            id=first_workspace_id,
            organization_id=organization_id,
            name="First",
            slug="first",
            created_by=actor,
            created_at=NOW,
            updated_at=NOW,
        ),
        Workspace(
            id=second_workspace_id,
            organization_id=organization_id,
            name="Second",
            slug="second",
            created_by=actor,
            created_at=NOW,
            updated_at=NOW,
        ),
    ]
    owner = OrganizationMembership(
        id=_id(MembershipId, 30),
        organization_id=organization_id,
        user_id=owner_id,
        role=MembershipRole.OWNER,
        state=MembershipState.ACTIVE,
        created_by=actor,
        created_at=NOW,
        updated_at=NOW,
    )
    restricted = OrganizationMembership(
        id=_id(MembershipId, 31),
        organization_id=organization_id,
        user_id=restricted_id,
        role=MembershipRole.OPERATOR,
        state=MembershipState.ACTIVE,
        workspace_access=WorkspaceAccessMode.RESTRICTED,
        created_by=actor,
        created_at=NOW,
        updated_at=NOW,
    )
    workspace_grant = MembershipWorkspaceGrant(
        id=_id(MembershipWorkspaceGrantId, 32),
        membership_id=restricted.id,
        scope=WorkspaceScope(organization_id, first_workspace_id),
        created_by=actor,
        created_at=NOW,
    )
    with Session(database.migration_engine) as session, session.begin():
        session.add_all([user_to_record(user) for user in users])
        session.add_all(
            [organization_to_record(organization) for organization in organizations]
        )
        session.flush()
        session.add_all([workspace_to_record(workspace) for workspace in workspaces])
        session.add_all([membership_to_record(owner), membership_to_record(restricted)])
        session.flush()
        session.add(membership_workspace_grant_to_record(workspace_grant))
    return (
        owner_id,
        restricted_id,
        target_id,
        organization_id,
        other_organization_id,
        first_workspace_id,
        second_workspace_id,
        restricted.id,
    )


def test_human_facts_authorize_then_establish_rls_without_leaking(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    (
        owner_id,
        restricted_id,
        _target_id,
        organization_id,
        other_organization_id,
        first_workspace_id,
        second_workspace_id,
        _restricted_membership_id,
    ) = _seed(postgres_database)
    authorization = _authorization(runtime_session_factory)

    context = authorization.authorize(
        _human(restricted_id),
        organization_id,
        Permission.TRIAGE_RUN,
        workspace_id=first_workspace_id,
    )
    with authorized_tenant_transaction(runtime_session_factory, context) as session:
        assert session.scalars(select(WorkspaceRecord.id)).all() == [
            UUID(str(first_workspace_id)),
            UUID(str(second_workspace_id)),
        ]

    with runtime_session_factory.begin() as session:
        backend_pid = session.scalar(text("SELECT pg_backend_pid()"))
        assert session.scalars(select(OrganizationMembershipRecord.id)).all() == []
    with runtime_session_factory.begin() as session:
        assert session.scalar(text("SELECT pg_backend_pid()")) == backend_pid
        assert session.scalars(select(OrganizationMembershipRecord.id)).all() == []

    with pytest.raises(AuthorizationDenied):
        authorization.authorize(
            _human(restricted_id),
            organization_id,
            Permission.TRIAGE_RUN,
            workspace_id=second_workspace_id,
        )
    with pytest.raises(AuthorizationDenied):
        authorization.authorize(
            _human(owner_id), other_organization_id, Permission.ORGANIZATION_READ
        )

    with Session(postgres_database.migration_engine) as session, session.begin():
        record = session.get(
            OrganizationMembershipRecord, UUID(str(_restricted_membership_id))
        )
        record.state = MembershipState.SUSPENDED.value
    with pytest.raises(AuthorizationDenied):
        authorization.authorize(
            _human(restricted_id), organization_id, Permission.ORGANIZATION_READ
        )


def test_service_account_grant_is_durable_restricted_and_revocable(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    (
        owner_id,
        _restricted_id,
        _target_id,
        organization_id,
        _other_organization_id,
        first_workspace_id,
        second_workspace_id,
        _membership_id,
    ) = _seed(postgres_database)
    account_id = _id(ServiceAccountId, 40)
    actor = ActorReference(ActorKind.HUMAN, actor_id=owner_id)
    account = ServiceAccount(
        id=account_id,
        name="Integration",
        created_by=actor,
        created_at=NOW,
        updated_at=NOW,
    )
    grant = ServiceAccountGrant(
        id=_id(ServiceAccountGrantId, 41),
        service_account_id=account_id,
        organization_id=organization_id,
        permissions=frozenset({Permission.INCIDENT_READ}),
        workspace_access=WorkspaceAccessMode.RESTRICTED,
        created_by=actor,
        created_at=NOW,
        updated_at=NOW,
    )
    workspace_grant = ServiceAccountWorkspaceGrant(
        id=_id(ServiceAccountWorkspaceGrantId, 42),
        service_account_grant_id=grant.id,
        scope=WorkspaceScope(organization_id, first_workspace_id),
        created_by=actor,
        created_at=NOW,
    )
    with Session(postgres_database.migration_engine) as session, session.begin():
        session.add(service_account_to_record(account))
        session.flush()
        session.add(service_account_grant_to_record(grant))
        session.flush()
        session.add(service_account_workspace_grant_to_record(workspace_grant))

    authorization = _authorization(runtime_session_factory)
    authorization.authorize(
        _service_actor(account_id),
        organization_id,
        Permission.INCIDENT_READ,
        workspace_id=first_workspace_id,
    )
    with pytest.raises(AuthorizationDenied):
        authorization.authorize(
            _service_actor(account_id),
            organization_id,
            Permission.INCIDENT_READ,
            workspace_id=second_workspace_id,
        )
    with pytest.raises(AuthorizationDenied):
        authorization.authorize(
            _service_actor(account_id),
            organization_id,
            Permission.TRIAGE_RUN,
            workspace_id=first_workspace_id,
        )

    with Session(postgres_database.migration_engine) as session, session.begin():
        record = session.get(
            ServiceAccountAuthorizationGrantRecord, UUID(str(grant.id))
        )
        record.revoked_at = NOW
        record.revoked_by_kind = ActorKind.HUMAN.value
        record.revoked_by_id = UUID(str(owner_id))
    with pytest.raises(AuthorizationDenied):
        authorization.authorize(
            _service_actor(account_id),
            organization_id,
            Permission.INCIDENT_READ,
            workspace_id=first_workspace_id,
        )


def test_governance_change_and_audit_commit_atomically(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    (
        owner_id,
        _restricted_id,
        target_id,
        organization_id,
        _other_organization_id,
        _first_workspace_id,
        _second_workspace_id,
        _membership_id,
    ) = _seed(postgres_database)
    authorization = _authorization(runtime_session_factory)
    service = OrganizationGovernanceService(
        authorization,
        lambda context: PostgresGovernanceUnitOfWork(
            runtime_session_factory, context
        ),
        clock=lambda: NOW,
    )
    invited = service.invite_member(
        _human(owner_id),
        organization_id,
        user_id=target_id,
        role=MembershipRole.VIEWER,
    )
    assert invited.state is MembershipState.INVITED

    with Session(postgres_database.migration_engine) as session:
        assert session.scalar(select(func.count()).select_from(AuditEventRecord)) == 1
        event = session.scalar(select(AuditEventRecord))
        assert event.event_type == "membership.invited"
        assert event.actor_id == UUID(str(owner_id))
        assert event.organization_id == UUID(str(organization_id))
