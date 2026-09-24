"""Central authorization service and sealed tenant context."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.auth.context import ActorContext
from app.authorization.permissions import (
    ROLE_PERMISSIONS,
    WORKSPACE_SCOPED_PERMISSIONS,
    Permission,
    role_allows,
)
from app.domain.common import ActorKind, ActorReference
from app.domain.identifiers import (
    MembershipId,
    OrganizationId,
    ServiceAccountGrantId,
    WorkspaceId,
)
from app.domain.tenancy import MembershipRole, WorkspaceAccessMode


class AuthorizationDenied(Exception):
    """The authenticated actor is not authorized; details are intentionally generic."""


@dataclass(frozen=True, slots=True)
class HumanAuthorizationFacts:
    membership_id: MembershipId
    role: MembershipRole
    workspace_access: WorkspaceAccessMode
    workspace_allowed: bool


@dataclass(frozen=True, slots=True)
class ServiceAccountAuthorizationFacts:
    grant_id: ServiceAccountGrantId
    permissions: frozenset[Permission]
    workspace_access: WorkspaceAccessMode
    workspace_allowed: bool


class AuthorizationFactsRepository(Protocol):
    def human_facts(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId | None,
    ) -> HumanAuthorizationFacts | None: ...

    def service_account_facts(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId | None,
    ) -> ServiceAccountAuthorizationFacts | None: ...

    def invited_membership_id(
        self, actor: ActorContext, organization_id: OrganizationId
    ) -> MembershipId | None: ...

    def visible_organization_ids(
        self, actor: ActorContext
    ) -> tuple[OrganizationId, ...]: ...


class TenantResourceValidator(Protocol):
    def is_active(
        self,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId | None,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class SystemAuthorizationGrant:
    system_name: str
    workload_issuer: str
    workload_subject: str
    organization_id: OrganizationId
    permissions: frozenset[Permission]
    workspace_ids: frozenset[WorkspaceId] | None = None


_CONTEXT_SEAL = object()


@dataclass(frozen=True, slots=True)
class AuthorizedTenantContext:
    actor: ActorReference
    organization_id: OrganizationId
    workspace_id: WorkspaceId | None
    permission: Permission
    authorization_source_id: str
    _seal: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._seal is not _CONTEXT_SEAL:
            raise TypeError("AuthorizedTenantContext must come from AuthorizationService")


class AuthorizationService:
    def __init__(
        self,
        facts: AuthorizationFactsRepository,
        resources: TenantResourceValidator,
        *,
        system_grants: tuple[SystemAuthorizationGrant, ...] = (),
    ) -> None:
        self._facts = facts
        self._resources = resources
        self._system_grants = system_grants

    def authorize(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        permission: Permission,
        *,
        workspace_id: WorkspaceId | None = None,
    ) -> AuthorizedTenantContext:
        if permission in WORKSPACE_SCOPED_PERMISSIONS and workspace_id is None:
            self._deny()

        if actor.actor.kind is ActorKind.HUMAN:
            facts = self._facts.human_facts(actor, organization_id, workspace_id)
            if facts is None or not role_allows(facts.role, permission):
                self._deny()
            if not self._workspace_allowed(
                facts.workspace_access,
                facts.workspace_allowed,
                permission,
                workspace_id,
            ):
                self._deny()
            source_id = str(facts.membership_id)
        elif actor.actor.kind is ActorKind.SERVICE_ACCOUNT:
            facts = self._facts.service_account_facts(
                actor, organization_id, workspace_id
            )
            if facts is None or permission not in facts.permissions:
                self._deny()
            if not self._workspace_allowed(
                facts.workspace_access,
                facts.workspace_allowed,
                permission,
                workspace_id,
            ):
                self._deny()
            source_id = str(facts.grant_id)
        else:
            source_id = self._authorize_system(
                actor, organization_id, workspace_id, permission
            )

        if not self._resources.is_active(organization_id, workspace_id):
            self._deny()
        return self._issue(actor, organization_id, workspace_id, permission, source_id)

    def authorize_organization_creation(
        self, actor: ActorContext, organization_id: OrganizationId
    ) -> AuthorizedTenantContext:
        if actor.actor.kind is not ActorKind.HUMAN:
            self._deny()
        return self._issue(
            actor,
            organization_id,
            None,
            Permission.ORGANIZATION_CREATE,
            str(actor.actor.actor_id),
        )

    def authorize_workspace_creation(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
    ) -> AuthorizedTenantContext:
        organization_context = self.authorize(
            actor, organization_id, Permission.WORKSPACE_CREATE
        )
        return self._issue(
            actor,
            organization_id,
            workspace_id,
            Permission.WORKSPACE_CREATE,
            organization_context.authorization_source_id,
        )

    def authorize_invitation_acceptance(
        self, actor: ActorContext, organization_id: OrganizationId
    ) -> tuple[AuthorizedTenantContext, MembershipId]:
        if actor.actor.kind is not ActorKind.HUMAN:
            self._deny()
        membership_id = self._facts.invited_membership_id(actor, organization_id)
        if membership_id is None or not self._resources.is_active(organization_id, None):
            self._deny()
        context = self._issue(
            actor,
            organization_id,
            None,
            Permission.ORGANIZATION_READ,
            str(membership_id),
        )
        return context, membership_id

    def visible_organization_ids(
        self, actor: ActorContext
    ) -> tuple[OrganizationId, ...]:
        if actor.actor.kind is ActorKind.SYSTEM:
            candidates = tuple(
                dict.fromkeys(
                    grant.organization_id
                    for grant in self._system_grants
                    if grant.system_name == actor.actor.system_name
                    and grant.workload_issuer == actor.issuer
                    and grant.workload_subject == actor.external_subject
                    and Permission.ORGANIZATION_READ in grant.permissions
                )
            )
        else:
            candidates = self._facts.visible_organization_ids(actor)
        return tuple(
            organization_id
            for organization_id in candidates
            if self._resources.is_active(organization_id, None)
        )

    @staticmethod
    def _workspace_allowed(
        mode: WorkspaceAccessMode,
        selected_workspace_allowed: bool,
        permission: Permission,
        workspace_id: WorkspaceId | None,
    ) -> bool:
        if mode is WorkspaceAccessMode.ALL:
            return True
        if permission is Permission.WORKSPACE_CREATE:
            return False
        if workspace_id is None:
            return permission not in WORKSPACE_SCOPED_PERMISSIONS
        return selected_workspace_allowed

    def _authorize_system(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId | None,
        permission: Permission,
    ) -> str:
        for grant in self._system_grants:
            if (
                grant.system_name == actor.actor.system_name
                and grant.workload_issuer == actor.issuer
                and grant.workload_subject == actor.external_subject
                and grant.organization_id == organization_id
                and permission in grant.permissions
                and (
                    workspace_id is None
                    or grant.workspace_ids is None
                    or workspace_id in grant.workspace_ids
                )
            ):
                return f"system:{grant.system_name}"
        self._deny()

    @staticmethod
    def _issue(
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId | None,
        permission: Permission,
        source_id: str,
    ) -> AuthorizedTenantContext:
        return AuthorizedTenantContext(
            actor=actor.actor,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permission=permission,
            authorization_source_id=source_id,
            _seal=_CONTEXT_SEAL,
        )

    @staticmethod
    def _deny() -> None:
        raise AuthorizationDenied("Access denied")


def permissions_for_role(role: MembershipRole) -> frozenset[Permission]:
    return ROLE_PERMISSIONS[role]
