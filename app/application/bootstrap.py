"""Authenticated hosted-web bootstrap assembled from authoritative services."""

from __future__ import annotations

from dataclasses import dataclass

from app.application.governance import OrganizationGovernanceService
from app.application.workspaces import HostedWorkspaceService
from app.auth.context import ActorContext
from app.authorization.permissions import ROLE_PERMISSIONS, Permission
from app.authorization.service import AuthorizationService
from app.domain.common import ActorKind
from app.domain.tenancy import WorkspaceAccessMode


@dataclass(frozen=True, slots=True)
class BootstrapWorkspace:
    id: str
    name: str
    slug: str


@dataclass(frozen=True, slots=True)
class BootstrapOrganization:
    id: str
    name: str
    slug: str
    role: str
    membership_state: str
    permissions: tuple[str, ...]
    workspaces: tuple[BootstrapWorkspace, ...]


@dataclass(frozen=True, slots=True)
class HostedBootstrap:
    user_id: str
    organizations: tuple[BootstrapOrganization, ...]


class HostedBootstrapService:
    """Return only scopes the backend has authorized for the authenticated human."""

    def __init__(
        self,
        authorization: AuthorizationService,
        governance: OrganizationGovernanceService,
        workspaces: HostedWorkspaceService,
    ) -> None:
        self._authorization = authorization
        self._governance = governance
        self._workspaces = workspaces

    def get(self, actor: ActorContext) -> HostedBootstrap:
        if actor.actor.kind is not ActorKind.HUMAN or actor.actor.actor_id is None:
            raise PermissionError("Hosted browser bootstrap requires a human actor")

        organizations: list[BootstrapOrganization] = []
        for organization in self._governance.list_organizations(actor):
            facts = self._authorization.human_membership_facts(actor, organization.id)
            if facts is None:
                continue
            visible_workspaces = self._workspaces.list_visible_page(
                actor, organization.id, limit=100
            ).items
            permissions = set(ROLE_PERMISSIONS[facts.role])
            if facts.workspace_access is WorkspaceAccessMode.RESTRICTED:
                permissions.discard(Permission.WORKSPACE_CREATE)
            organizations.append(
                BootstrapOrganization(
                    id=str(organization.id),
                    name=organization.name,
                    slug=organization.slug,
                    role=facts.role.value,
                    membership_state="active",
                    permissions=tuple(
                        sorted(permission.value for permission in permissions)
                    ),
                    workspaces=tuple(
                        BootstrapWorkspace(str(item.id), item.name, item.slug)
                        for item in visible_workspaces
                    ),
                )
            )
        return HostedBootstrap(str(actor.actor.actor_id), tuple(organizations))
