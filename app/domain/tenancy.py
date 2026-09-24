"""Identity, organization, membership, and workspace domain concepts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from app.domain.common import (
    ActorReference,
    DomainInvariantError,
    WorkspaceScope,
    require_transition,
    utc_now,
    validate_timestamps,
)
from app.domain.identifiers import MembershipId, OrganizationId, UserId, WorkspaceId


class OrganizationState(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class WorkspaceState(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class MembershipRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class MembershipState(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class WorkspaceAccessMode(StrEnum):
    ALL = "all"
    RESTRICTED = "restricted"


_MEMBERSHIP_TRANSITIONS = {
    MembershipState.INVITED: frozenset({MembershipState.ACTIVE, MembershipState.REVOKED}),
    MembershipState.ACTIVE: frozenset({MembershipState.SUSPENDED, MembershipState.REVOKED}),
    MembershipState.SUSPENDED: frozenset({MembershipState.ACTIVE, MembershipState.REVOKED}),
    MembershipState.REVOKED: frozenset({MembershipState.INVITED}),
}


@dataclass(frozen=True, slots=True)
class User:
    id: UserId
    email: str
    display_name: str
    identity_provider: str
    provider_subject: str
    created_at: datetime
    disabled_at: datetime | None = None

    def __post_init__(self) -> None:
        if "@" not in self.email or not self.email.strip():
            raise DomainInvariantError("User email must be non-empty and email-shaped")
        for field_name in ("display_name", "identity_provider", "provider_subject"):
            if not str(getattr(self, field_name)).strip():
                raise DomainInvariantError(f"User {field_name} cannot be blank")
        validate_timestamps(self.created_at, self.disabled_at or self.created_at)


@dataclass(frozen=True, slots=True)
class Organization:
    id: OrganizationId
    name: str
    slug: str
    created_by: ActorReference
    created_at: datetime
    updated_at: datetime
    state: OrganizationState = OrganizationState.ACTIVE

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.slug.strip():
            raise DomainInvariantError("Organization name and slug cannot be blank")
        validate_timestamps(self.created_at, self.updated_at)

    def archive(self, *, at: datetime | None = None) -> Organization:
        if self.state is OrganizationState.ARCHIVED:
            raise DomainInvariantError("Organization is already archived")
        return replace(self, state=OrganizationState.ARCHIVED, updated_at=at or utc_now())


@dataclass(frozen=True, slots=True)
class OrganizationMembership:
    id: MembershipId
    organization_id: OrganizationId
    user_id: UserId
    role: MembershipRole
    state: MembershipState
    created_by: ActorReference
    created_at: datetime
    updated_at: datetime
    workspace_access: WorkspaceAccessMode = WorkspaceAccessMode.ALL

    def __post_init__(self) -> None:
        validate_timestamps(self.created_at, self.updated_at)
        if self.role is MembershipRole.OWNER and self.workspace_access is not WorkspaceAccessMode.ALL:
            raise DomainInvariantError("Owner memberships must have unrestricted workspace access")

    def transition(
        self,
        target: MembershipState,
        *,
        at: datetime | None = None,
    ) -> OrganizationMembership:
        require_transition("OrganizationMembership", self.state, target, _MEMBERSHIP_TRANSITIONS)
        return replace(self, state=target, updated_at=at or utc_now())


@dataclass(frozen=True, slots=True)
class Workspace:
    id: WorkspaceId
    organization_id: OrganizationId
    name: str
    slug: str
    created_by: ActorReference
    created_at: datetime
    updated_at: datetime
    state: WorkspaceState = WorkspaceState.ACTIVE

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.slug.strip():
            raise DomainInvariantError("Workspace name and slug cannot be blank")
        validate_timestamps(self.created_at, self.updated_at)

    @property
    def scope(self) -> WorkspaceScope:
        return WorkspaceScope(self.organization_id, self.id)

    def archive(self, *, at: datetime | None = None) -> Workspace:
        if self.state is WorkspaceState.ARCHIVED:
            raise DomainInvariantError("Workspace is already archived")
        return replace(self, state=WorkspaceState.ARCHIVED, updated_at=at or utc_now())
