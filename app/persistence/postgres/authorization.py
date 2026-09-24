"""PostgreSQL authorization facts and tenant-resource validation."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.auth.context import ActorContext
from app.authorization.permissions import Permission
from app.authorization.service import (
    HumanAuthorizationFacts,
    ServiceAccountAuthorizationFacts,
)
from app.domain.identifiers import (
    MembershipId,
    OrganizationId,
    ServiceAccountGrantId,
    WorkspaceId,
)
from app.domain.tenancy import (
    MembershipRole,
    MembershipState,
    OrganizationState,
    WorkspaceAccessMode,
    WorkspaceState,
)
from app.persistence.postgres.models import (
    MembershipWorkspaceGrantRecord,
    OrganizationMembershipRecord,
    OrganizationRecord,
    ServiceAccountAuthorizationGrantRecord,
    ServiceAccountRecord,
    ServiceAccountWorkspaceGrantRecord,
    UserRecord,
    WorkspaceRecord,
)
from app.persistence.postgres.tenant import (
    TenantContext,
    actor_transaction,
    tenant_transaction,
)


class PostgresAuthorizationFactsRepository:
    """Actor-self lookups protected by dedicated SELECT-only RLS policies."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def human_facts(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId | None,
    ) -> HumanAuthorizationFacts | None:
        if actor.actor.actor_id is None:
            return None
        with actor_transaction(self._session_factory, actor) as session:
            user = session.get(UserRecord, UUID(str(actor.actor.actor_id)))
            if user is None or user.disabled_at is not None:
                return None
            membership = session.scalar(
                select(OrganizationMembershipRecord).where(
                    OrganizationMembershipRecord.organization_id
                    == UUID(str(organization_id)),
                    OrganizationMembershipRecord.user_id
                    == UUID(str(actor.actor.actor_id)),
                    OrganizationMembershipRecord.state == MembershipState.ACTIVE.value,
                )
            )
            if membership is None:
                return None
            return HumanAuthorizationFacts(
                membership_id=MembershipId(str(membership.id)),
                role=MembershipRole(membership.role),
                workspace_access=WorkspaceAccessMode(membership.workspace_access),
                workspace_allowed=self._membership_workspace_allowed(
                    session, membership.id, workspace_id
                ),
            )

    def service_account_facts(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId | None,
    ) -> ServiceAccountAuthorizationFacts | None:
        if actor.actor.actor_id is None:
            return None
        with actor_transaction(self._session_factory, actor) as session:
            account = session.get(ServiceAccountRecord, UUID(str(actor.actor.actor_id)))
            if account is None or account.disabled_at is not None:
                return None
            grant = session.scalar(
                select(ServiceAccountAuthorizationGrantRecord).where(
                    ServiceAccountAuthorizationGrantRecord.organization_id
                    == UUID(str(organization_id)),
                    ServiceAccountAuthorizationGrantRecord.service_account_id
                    == UUID(str(actor.actor.actor_id)),
                    ServiceAccountAuthorizationGrantRecord.revoked_at.is_(None),
                )
            )
            if grant is None:
                return None
            try:
                permissions = frozenset(Permission(value) for value in grant.permissions)
            except ValueError:
                return None
            return ServiceAccountAuthorizationFacts(
                grant_id=ServiceAccountGrantId(str(grant.id)),
                permissions=permissions,
                workspace_access=WorkspaceAccessMode(grant.workspace_access),
                workspace_allowed=self._service_workspace_allowed(
                    session, grant.id, workspace_id
                ),
            )

    def invited_membership_id(
        self, actor: ActorContext, organization_id: OrganizationId
    ) -> MembershipId | None:
        if actor.actor.actor_id is None:
            return None
        with actor_transaction(self._session_factory, actor) as session:
            record = session.scalar(
                select(OrganizationMembershipRecord.id).where(
                    OrganizationMembershipRecord.organization_id
                    == UUID(str(organization_id)),
                    OrganizationMembershipRecord.user_id
                    == UUID(str(actor.actor.actor_id)),
                    OrganizationMembershipRecord.state
                    == MembershipState.INVITED.value,
                )
            )
            return MembershipId(str(record)) if record else None

    def visible_organization_ids(
        self, actor: ActorContext
    ) -> tuple[OrganizationId, ...]:
        if actor.actor.actor_id is None:
            return ()
        with actor_transaction(self._session_factory, actor) as session:
            if actor.actor.kind.value == "human":
                values = session.scalars(
                    select(OrganizationMembershipRecord.organization_id).where(
                        OrganizationMembershipRecord.user_id
                        == UUID(str(actor.actor.actor_id)),
                        OrganizationMembershipRecord.state
                        == MembershipState.ACTIVE.value,
                    )
                ).all()
            elif actor.actor.kind.value == "service_account":
                values = session.scalars(
                    select(ServiceAccountAuthorizationGrantRecord.organization_id).where(
                        ServiceAccountAuthorizationGrantRecord.service_account_id
                        == UUID(str(actor.actor.actor_id)),
                        ServiceAccountAuthorizationGrantRecord.revoked_at.is_(None),
                    )
                ).all()
            else:
                values = []
        return tuple(OrganizationId(str(value)) for value in values)

    @staticmethod
    def _membership_workspace_allowed(
        session: Session,
        membership_id: UUID,
        workspace_id: WorkspaceId | None,
    ) -> bool:
        if workspace_id is None:
            return False
        return session.scalar(
            select(MembershipWorkspaceGrantRecord.id).where(
                MembershipWorkspaceGrantRecord.membership_id == membership_id,
                MembershipWorkspaceGrantRecord.workspace_id
                == UUID(str(workspace_id)),
            )
        ) is not None

    @staticmethod
    def _service_workspace_allowed(
        session: Session,
        grant_id: UUID,
        workspace_id: WorkspaceId | None,
    ) -> bool:
        if workspace_id is None:
            return False
        return session.scalar(
            select(ServiceAccountWorkspaceGrantRecord.id).where(
                ServiceAccountWorkspaceGrantRecord.service_account_grant_id
                == grant_id,
                ServiceAccountWorkspaceGrantRecord.workspace_id
                == UUID(str(workspace_id)),
            )
        ) is not None


class PostgresTenantResourceValidator:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def is_active(
        self,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId | None,
    ) -> bool:
        with tenant_transaction(
            self._session_factory, TenantContext(organization_id, workspace_id)
        ) as session:
            organization = session.get(
                OrganizationRecord, UUID(str(organization_id))
            )
            if organization is None or organization.state != OrganizationState.ACTIVE.value:
                return False
            if workspace_id is None:
                return True
            workspace = session.get(WorkspaceRecord, UUID(str(workspace_id)))
            return bool(
                workspace
                and workspace.organization_id == UUID(str(organization_id))
                and workspace.state == WorkspaceState.ACTIVE.value
            )
