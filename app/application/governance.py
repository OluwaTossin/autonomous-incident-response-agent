"""Organization governance and authorization-sensitive lifecycle services."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol, Self

from app.auth.context import ActorContext
from app.authorization.models import (
    MembershipWorkspaceGrant,
    ServiceAccountGrant,
    ServiceAccountWorkspaceGrant,
)
from app.authorization.permissions import Permission
from app.authorization.service import AuthorizationDenied, AuthorizationService
from app.domain.common import (
    ActorKind,
    CorrelationContext,
    OrganizationScope,
    WorkspaceScope,
)
from app.domain.events import AuditEvent
from app.domain.identifiers import (
    AuditEventId,
    CorrelationId,
    MembershipId,
    MembershipWorkspaceGrantId,
    OrganizationId,
    ServiceAccountGrantId,
    ServiceAccountId,
    ServiceAccountWorkspaceGrantId,
    UserId,
    WorkspaceId,
)
from app.domain.tenancy import (
    MembershipRole,
    MembershipState,
    Organization,
    OrganizationMembership,
    WorkspaceAccessMode,
)


class GovernanceConflict(Exception):
    """A requested governance change violates a durable business invariant."""


class OrganizationRepository(Protocol):
    def add(self, organization: Organization) -> None: ...
    def get(self, organization_id: OrganizationId) -> Organization | None: ...


class MembershipRepository(Protocol):
    def add(self, membership: OrganizationMembership) -> None: ...
    def save(self, membership: OrganizationMembership) -> None: ...
    def get(self, membership_id: MembershipId) -> OrganizationMembership | None: ...
    def get_for_user(
        self, organization_id: OrganizationId, user_id: UserId
    ) -> OrganizationMembership | None: ...
    def list(self) -> Sequence[OrganizationMembership]: ...
    def count_active_owners(self) -> int: ...
    def lock_organization(self, organization_id: OrganizationId) -> None: ...


class MembershipWorkspaceGrantRepository(Protocol):
    def replace(
        self,
        membership_id: MembershipId,
        grants: list[MembershipWorkspaceGrant],
    ) -> None: ...


class ServiceAccountGrantRepository(Protocol):
    def add(self, grant: ServiceAccountGrant) -> None: ...
    def save(self, grant: ServiceAccountGrant) -> None: ...
    def get(self, grant_id: ServiceAccountGrantId) -> ServiceAccountGrant | None: ...
    def get_active(
        self,
        organization_id: OrganizationId,
        service_account_id: ServiceAccountId,
    ) -> ServiceAccountGrant | None: ...


class ServiceAccountWorkspaceGrantRepository(Protocol):
    def replace(
        self,
        grant_id: ServiceAccountGrantId,
        grants: list[ServiceAccountWorkspaceGrant],
    ) -> None: ...


class GovernanceUnitOfWork(Protocol):
    organizations: OrganizationRepository
    memberships: MembershipRepository
    membership_workspace_grants: MembershipWorkspaceGrantRepository
    service_account_grants: ServiceAccountGrantRepository
    service_account_workspace_grants: ServiceAccountWorkspaceGrantRepository
    audit_events: object

    def __enter__(self) -> Self: ...
    def __exit__(self, exc_type, exc_value, traceback) -> None: ...


GovernanceUnitOfWorkFactory = Callable[[object], GovernanceUnitOfWork]


class OrganizationGovernanceService:
    def __init__(
        self,
        authorization: AuthorizationService,
        uow_factory: GovernanceUnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._authorization = authorization
        self._uow_factory = uow_factory
        self._clock = clock

    def create_organization(
        self,
        actor: ActorContext,
        *,
        name: str,
        slug: str,
        correlation: CorrelationContext | None = None,
    ) -> Organization:
        if actor.actor.kind is not ActorKind.HUMAN or actor.actor.actor_id is None:
            raise AuthorizationDenied("Access denied")
        now = self._clock()
        organization_id = OrganizationId.new()
        context = self._authorization.authorize_organization_creation(
            actor, organization_id
        )
        organization = Organization(
            id=organization_id,
            name=name,
            slug=slug,
            created_by=actor.actor,
            created_at=now,
            updated_at=now,
        )
        membership = OrganizationMembership(
            id=MembershipId.new(),
            organization_id=organization_id,
            user_id=UserId(str(actor.actor.actor_id)),
            role=MembershipRole.OWNER,
            state=MembershipState.ACTIVE,
            workspace_access=WorkspaceAccessMode.ALL,
            created_by=actor.actor,
            created_at=now,
            updated_at=now,
        )
        with self._uow_factory(context) as uow:
            uow.organizations.add(organization)
            uow.memberships.add(membership)
            self._audit(
                uow,
                actor,
                organization_id,
                "organization.created",
                "organization",
                str(organization_id),
                correlation,
            )
        return organization

    def visible_organization_ids(
        self, actor: ActorContext
    ) -> tuple[OrganizationId, ...]:
        return self._authorization.visible_organization_ids(actor)

    def get_organization(
        self, actor: ActorContext, organization_id: OrganizationId
    ) -> Organization:
        context = self._authorization.authorize(
            actor, organization_id, Permission.ORGANIZATION_READ
        )
        with self._uow_factory(context) as uow:
            organization = uow.organizations.get(organization_id)
            if organization is None:
                raise AuthorizationDenied("Access denied")
            return organization

    def list_organizations(self, actor: ActorContext) -> tuple[Organization, ...]:
        return tuple(
            self.get_organization(actor, organization_id)
            for organization_id in self.visible_organization_ids(actor)
        )

    def list_memberships(
        self, actor: ActorContext, organization_id: OrganizationId
    ) -> tuple[OrganizationMembership, ...]:
        context = self._authorization.authorize(
            actor, organization_id, Permission.MEMBERSHIP_READ
        )
        with self._uow_factory(context) as uow:
            return tuple(uow.memberships.list())

    def invite_member(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        *,
        user_id: UserId,
        role: MembershipRole,
        workspace_access: WorkspaceAccessMode = WorkspaceAccessMode.ALL,
        workspace_ids: Sequence[WorkspaceId] = (),
        correlation: CorrelationContext | None = None,
    ) -> OrganizationMembership:
        context = self._authorization.authorize(
            actor, organization_id, Permission.MEMBERSHIP_INVITE
        )
        self._validate_workspace_selection(actor, organization_id, workspace_access, workspace_ids)
        now = self._clock()
        with self._uow_factory(context) as uow:
            self._guard_target_role(uow, context.authorization_source_id, role)
            current = uow.memberships.get_for_user(organization_id, user_id)
            if current is not None and current.state is not MembershipState.REVOKED:
                raise GovernanceConflict("Membership already exists")
            if current is None:
                membership = OrganizationMembership(
                    id=MembershipId.new(),
                    organization_id=organization_id,
                    user_id=user_id,
                    role=role,
                    state=MembershipState.INVITED,
                    workspace_access=workspace_access,
                    created_by=actor.actor,
                    created_at=now,
                    updated_at=now,
                )
                uow.memberships.add(membership)
            else:
                membership = replace(
                    current.transition(MembershipState.INVITED, at=now),
                    role=role,
                    workspace_access=workspace_access,
                )
                uow.memberships.save(membership)
            self._replace_membership_workspace_grants(
                uow, actor, membership, workspace_ids, now
            )
            self._audit_membership(
                uow, actor, membership, "membership.invited", correlation
            )
            return membership

    def accept_invitation(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        *,
        correlation: CorrelationContext | None = None,
    ) -> OrganizationMembership:
        context, membership_id = self._authorization.authorize_invitation_acceptance(
            actor, organization_id
        )
        with self._uow_factory(context) as uow:
            membership = self._required_membership(uow, membership_id)
            membership = membership.transition(MembershipState.ACTIVE, at=self._clock())
            uow.memberships.save(membership)
            self._audit_membership(
                uow, actor, membership, "membership.activated", correlation
            )
            return membership

    def change_role(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        membership_id: MembershipId,
        role: MembershipRole,
        *,
        correlation: CorrelationContext | None = None,
    ) -> OrganizationMembership:
        context = self._authorization.authorize(
            actor, organization_id, Permission.MEMBERSHIP_UPDATE
        )
        with self._uow_factory(context) as uow:
            uow.memberships.lock_organization(organization_id)
            target = self._required_membership(uow, membership_id)
            self._guard_target_role(uow, context.authorization_source_id, target.role, role)
            if target.role is MembershipRole.OWNER and role is not MembershipRole.OWNER:
                self._require_another_owner(uow)
            updated = replace(
                target,
                role=role,
                workspace_access=(
                    WorkspaceAccessMode.ALL
                    if role is MembershipRole.OWNER
                    else target.workspace_access
                ),
                updated_at=self._clock(),
            )
            uow.memberships.save(updated)
            if role is MembershipRole.OWNER:
                uow.membership_workspace_grants.replace(updated.id, [])
            self._audit_membership(
                uow,
                actor,
                updated,
                "membership.role_changed",
                correlation,
                (("old_role", target.role.value), ("new_role", role.value)),
            )
            return updated

    def suspend_member(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        membership_id: MembershipId,
        *,
        correlation: CorrelationContext | None = None,
    ) -> OrganizationMembership:
        return self._change_membership_state(
            actor,
            organization_id,
            membership_id,
            MembershipState.SUSPENDED,
            Permission.MEMBERSHIP_UPDATE,
            "membership.suspended",
            correlation,
        )

    def remove_member(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        membership_id: MembershipId,
        *,
        correlation: CorrelationContext | None = None,
    ) -> OrganizationMembership:
        return self._change_membership_state(
            actor,
            organization_id,
            membership_id,
            MembershipState.REVOKED,
            Permission.MEMBERSHIP_REMOVE,
            "membership.removed",
            correlation,
        )

    def transfer_ownership(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        target_membership_id: MembershipId,
        *,
        correlation: CorrelationContext | None = None,
    ) -> tuple[OrganizationMembership, OrganizationMembership]:
        context = self._authorization.authorize(
            actor, organization_id, Permission.ORGANIZATION_TRANSFER_OWNERSHIP
        )
        with self._uow_factory(context) as uow:
            uow.memberships.lock_organization(organization_id)
            current = self._actor_membership(uow, context.authorization_source_id)
            target = self._required_membership(uow, target_membership_id)
            if current.role is not MembershipRole.OWNER:
                raise AuthorizationDenied("Access denied")
            if target.state is not MembershipState.ACTIVE or target.id == current.id:
                raise GovernanceConflict("Ownership target must be another active member")
            now = self._clock()
            new_owner = replace(
                target,
                role=MembershipRole.OWNER,
                workspace_access=WorkspaceAccessMode.ALL,
                updated_at=now,
            )
            former_owner = replace(
                current, role=MembershipRole.ADMIN, updated_at=now
            )
            uow.memberships.save(new_owner)
            uow.memberships.save(former_owner)
            uow.membership_workspace_grants.replace(new_owner.id, [])
            self._audit_membership(
                uow,
                actor,
                new_owner,
                "organization.ownership_transferred",
                correlation,
                (("from_membership_id", str(current.id)),),
            )
            return former_owner, new_owner

    def set_workspace_restrictions(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        membership_id: MembershipId,
        mode: WorkspaceAccessMode,
        workspace_ids: Sequence[WorkspaceId] = (),
        *,
        correlation: CorrelationContext | None = None,
    ) -> OrganizationMembership:
        context = self._authorization.authorize(
            actor, organization_id, Permission.MEMBERSHIP_UPDATE
        )
        self._validate_workspace_selection(actor, organization_id, mode, workspace_ids)
        with self._uow_factory(context) as uow:
            target = self._required_membership(uow, membership_id)
            self._guard_target_role(uow, context.authorization_source_id, target.role)
            if target.role is MembershipRole.OWNER and mode is WorkspaceAccessMode.RESTRICTED:
                raise GovernanceConflict("Owner memberships cannot be restricted")
            updated = replace(target, workspace_access=mode, updated_at=self._clock())
            uow.memberships.save(updated)
            self._replace_membership_workspace_grants(
                uow, actor, updated, workspace_ids, self._clock()
            )
            self._audit_membership(
                uow,
                actor,
                updated,
                "membership.workspace_restrictions_changed",
                correlation,
                (("workspace_access", mode.value),),
            )
            return updated

    def grant_service_account(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        service_account_id: ServiceAccountId,
        permissions: frozenset[Permission],
        *,
        workspace_access: WorkspaceAccessMode = WorkspaceAccessMode.ALL,
        workspace_ids: Sequence[WorkspaceId] = (),
        correlation: CorrelationContext | None = None,
    ) -> ServiceAccountGrant:
        context = self._authorization.authorize(
            actor, organization_id, Permission.SERVICE_ACCOUNT_MANAGE
        )
        self._validate_workspace_selection(
            actor, organization_id, workspace_access, workspace_ids
        )
        now = self._clock()
        grant = ServiceAccountGrant(
            id=ServiceAccountGrantId.new(),
            service_account_id=service_account_id,
            organization_id=organization_id,
            permissions=permissions,
            workspace_access=workspace_access,
            created_by=actor.actor,
            created_at=now,
            updated_at=now,
        )
        with self._uow_factory(context) as uow:
            if uow.service_account_grants.get_active(
                organization_id, service_account_id
            ) is not None:
                raise GovernanceConflict("Active service-account grant already exists")
            uow.service_account_grants.add(grant)
            self._replace_service_workspace_grants(
                uow, actor, grant, workspace_ids, now
            )
            self._audit(
                uow,
                actor,
                organization_id,
                "service_account.grant_created",
                "service_account_grant",
                str(grant.id),
                correlation,
                details=(("service_account_id", str(service_account_id)),),
            )
        return grant

    def revoke_service_account_grant(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        grant_id: ServiceAccountGrantId,
        *,
        correlation: CorrelationContext | None = None,
    ) -> ServiceAccountGrant:
        context = self._authorization.authorize(
            actor, organization_id, Permission.SERVICE_ACCOUNT_MANAGE
        )
        with self._uow_factory(context) as uow:
            grant = uow.service_account_grants.get(grant_id)
            if grant is None or grant.organization_id != organization_id:
                raise GovernanceConflict("Service-account grant not found")
            revoked = grant.revoke(actor=actor.actor, at=self._clock())
            uow.service_account_grants.save(revoked)
            self._audit(
                uow,
                actor,
                organization_id,
                "service_account.grant_revoked",
                "service_account_grant",
                str(grant.id),
                correlation,
            )
            return revoked

    def _change_membership_state(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        membership_id: MembershipId,
        state: MembershipState,
        permission: Permission,
        event_type: str,
        correlation: CorrelationContext | None,
    ) -> OrganizationMembership:
        context = self._authorization.authorize(actor, organization_id, permission)
        with self._uow_factory(context) as uow:
            uow.memberships.lock_organization(organization_id)
            target = self._required_membership(uow, membership_id)
            self._guard_target_role(uow, context.authorization_source_id, target.role)
            if target.role is MembershipRole.OWNER:
                self._require_another_owner(uow)
            updated = target.transition(state, at=self._clock())
            uow.memberships.save(updated)
            self._audit_membership(uow, actor, updated, event_type, correlation)
            return updated

    def _validate_workspace_selection(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        mode: WorkspaceAccessMode,
        workspace_ids: Sequence[WorkspaceId],
    ) -> None:
        if mode is WorkspaceAccessMode.ALL and workspace_ids:
            raise GovernanceConflict("Unrestricted access cannot include workspace grants")
        if mode is WorkspaceAccessMode.RESTRICTED and not workspace_ids:
            raise GovernanceConflict("Restricted access requires at least one workspace")
        if len(set(workspace_ids)) != len(workspace_ids):
            raise GovernanceConflict("Workspace grants must be unique")
        for workspace_id in workspace_ids:
            self._authorization.authorize(
                actor,
                organization_id,
                Permission.WORKSPACE_READ,
                workspace_id=workspace_id,
            )

    @staticmethod
    def _required_membership(
        uow: GovernanceUnitOfWork, membership_id: MembershipId
    ) -> OrganizationMembership:
        membership = uow.memberships.get(membership_id)
        if membership is None:
            raise GovernanceConflict("Membership not found")
        return membership

    @classmethod
    def _actor_membership(
        cls, uow: GovernanceUnitOfWork, source_id: str
    ) -> OrganizationMembership:
        try:
            membership_id = MembershipId(source_id)
        except (TypeError, ValueError) as exc:
            raise AuthorizationDenied("Access denied") from exc
        membership = cls._required_membership(uow, membership_id)
        if membership.state is not MembershipState.ACTIVE:
            raise AuthorizationDenied("Access denied")
        return membership

    @classmethod
    def _guard_target_role(
        cls,
        uow: GovernanceUnitOfWork,
        source_id: str,
        current_role: MembershipRole,
        new_role: MembershipRole | None = None,
    ) -> None:
        if source_id.startswith("system:"):
            return
        actor_membership = cls._actor_membership(uow, source_id)
        if actor_membership.role is MembershipRole.ADMIN and (
            current_role is MembershipRole.OWNER or new_role is MembershipRole.OWNER
        ):
            raise AuthorizationDenied("Access denied")

    @staticmethod
    def _require_another_owner(uow: GovernanceUnitOfWork) -> None:
        if uow.memberships.count_active_owners() <= 1:
            raise GovernanceConflict("Every organization requires an active Owner")

    @staticmethod
    def _replace_membership_workspace_grants(
        uow: GovernanceUnitOfWork,
        actor: ActorContext,
        membership: OrganizationMembership,
        workspace_ids: Sequence[WorkspaceId],
        now: datetime,
    ) -> None:
        grants = [
            MembershipWorkspaceGrant(
                id=MembershipWorkspaceGrantId.new(),
                membership_id=membership.id,
                scope=WorkspaceScope(membership.organization_id, workspace_id),
                created_by=actor.actor,
                created_at=now,
            )
            for workspace_id in workspace_ids
        ]
        uow.membership_workspace_grants.replace(membership.id, grants)

    @staticmethod
    def _replace_service_workspace_grants(
        uow: GovernanceUnitOfWork,
        actor: ActorContext,
        grant: ServiceAccountGrant,
        workspace_ids: Sequence[WorkspaceId],
        now: datetime,
    ) -> None:
        grants = [
            ServiceAccountWorkspaceGrant(
                id=ServiceAccountWorkspaceGrantId.new(),
                service_account_grant_id=grant.id,
                scope=WorkspaceScope(grant.organization_id, workspace_id),
                created_by=actor.actor,
                created_at=now,
            )
            for workspace_id in workspace_ids
        ]
        uow.service_account_workspace_grants.replace(grant.id, grants)

    def _audit_membership(
        self,
        uow: GovernanceUnitOfWork,
        actor: ActorContext,
        membership: OrganizationMembership,
        event_type: str,
        correlation: CorrelationContext | None,
        details: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self._audit(
            uow,
            actor,
            membership.organization_id,
            event_type,
            "organization_membership",
            str(membership.id),
            correlation,
            details=details,
        )

    def _audit(
        self,
        uow: GovernanceUnitOfWork,
        actor: ActorContext,
        organization_id: OrganizationId,
        event_type: str,
        target_type: str,
        target_id: str,
        correlation: CorrelationContext | None,
        *,
        details: tuple[tuple[str, str], ...] = (),
    ) -> None:
        uow.audit_events.add(
            AuditEvent(
                id=AuditEventId.new(),
                organization_scope=OrganizationScope(organization_id),
                event_type=event_type,
                target_type=target_type,
                target_id=target_id,
                actor=actor.actor,
                occurred_at=self._clock(),
                correlation=correlation
                or CorrelationContext(CorrelationId.new()),
                details=details,
            )
        )
