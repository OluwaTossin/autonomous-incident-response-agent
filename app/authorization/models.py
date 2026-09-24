"""Framework-independent authorization grants."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from app.authorization.permissions import (
    SERVICE_ACCOUNT_GRANTABLE_PERMISSIONS,
    Permission,
)
from app.domain.common import ActorReference, DomainInvariantError, WorkspaceScope, require_aware
from app.domain.identifiers import (
    MembershipId,
    MembershipWorkspaceGrantId,
    OrganizationId,
    ServiceAccountGrantId,
    ServiceAccountId,
    ServiceAccountWorkspaceGrantId,
)
from app.domain.tenancy import WorkspaceAccessMode


@dataclass(frozen=True, slots=True)
class MembershipWorkspaceGrant:
    id: MembershipWorkspaceGrantId
    membership_id: MembershipId
    scope: WorkspaceScope
    created_by: ActorReference
    created_at: datetime

    def __post_init__(self) -> None:
        require_aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class ServiceAccountGrant:
    id: ServiceAccountGrantId
    service_account_id: ServiceAccountId
    organization_id: OrganizationId
    permissions: frozenset[Permission]
    workspace_access: WorkspaceAccessMode
    created_by: ActorReference
    created_at: datetime
    updated_at: datetime
    revoked_at: datetime | None = None
    revoked_by: ActorReference | None = None

    def __post_init__(self) -> None:
        if not self.permissions:
            raise DomainInvariantError("Service-account grants require permissions")
        if not self.permissions <= SERVICE_ACCOUNT_GRANTABLE_PERMISSIONS:
            raise DomainInvariantError("Service-account grant contains prohibited permissions")
        require_aware(self.created_at, "created_at")
        require_aware(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise DomainInvariantError("updated_at cannot precede created_at")
        if self.revoked_at is not None:
            require_aware(self.revoked_at, "revoked_at")
        if (self.revoked_at is None) != (self.revoked_by is None):
            raise DomainInvariantError("revoked_at and revoked_by must be set together")

    @property
    def active(self) -> bool:
        return self.revoked_at is None

    def revoke(self, *, actor: ActorReference, at: datetime) -> ServiceAccountGrant:
        if not self.active:
            raise DomainInvariantError("Service-account grant is already revoked")
        return replace(self, revoked_at=at, revoked_by=actor, updated_at=at)


@dataclass(frozen=True, slots=True)
class ServiceAccountWorkspaceGrant:
    id: ServiceAccountWorkspaceGrantId
    service_account_grant_id: ServiceAccountGrantId
    scope: WorkspaceScope
    created_by: ActorReference
    created_at: datetime

    def __post_init__(self) -> None:
        require_aware(self.created_at, "created_at")
