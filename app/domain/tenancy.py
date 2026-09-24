"""Identity, organization, membership, and workspace domain concepts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping

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
    description: str | None = None
    version: int = 1

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.slug.strip():
            raise DomainInvariantError("Workspace name and slug cannot be blank")
        if len(self.name.strip()) > 200:
            raise DomainInvariantError("Workspace name cannot exceed 200 characters")
        if len(self.slug.strip()) > 100:
            raise DomainInvariantError("Workspace slug cannot exceed 100 characters")
        if self.description is not None and len(self.description.strip()) > 1000:
            raise DomainInvariantError("Workspace description cannot exceed 1000 characters")
        if self.version < 1:
            raise DomainInvariantError("Workspace version must be positive")
        validate_timestamps(self.created_at, self.updated_at)

    @property
    def scope(self) -> WorkspaceScope:
        return WorkspaceScope(self.organization_id, self.id)

    def update_metadata(
        self,
        *,
        name: str | None = None,
        slug: str | None = None,
        description: str | None = None,
        description_provided: bool = False,
        at: datetime | None = None,
    ) -> Workspace:
        if self.state is WorkspaceState.ARCHIVED:
            raise DomainInvariantError("Archived workspaces cannot be updated")
        return replace(
            self,
            name=self.name if name is None else name.strip(),
            slug=self.slug if slug is None else slug.strip(),
            description=(
                self.description
                if not description_provided
                else (description.strip() or None if description is not None else None)
            ),
            updated_at=at or utc_now(),
            version=self.version + 1,
        )

    def archive(self, *, at: datetime | None = None) -> Workspace:
        if self.state is WorkspaceState.ARCHIVED:
            raise DomainInvariantError("Workspace is already archived")
        return replace(
            self,
            state=WorkspaceState.ARCHIVED,
            updated_at=at or utc_now(),
            version=self.version + 1,
        )


WORKSPACE_CONFIG_SCHEMA_VERSION = 1
WORKSPACE_CONFIG_KEYS = frozenset({"rag_top_k", "llm_temperature"})


@dataclass(frozen=True, slots=True)
class WorkspaceConfiguration:
    scope: WorkspaceScope
    schema_version: int
    version: int
    rag_top_k: int
    llm_temperature: float
    updated_by: ActorReference
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != WORKSPACE_CONFIG_SCHEMA_VERSION:
            raise DomainInvariantError("Unsupported workspace configuration schema")
        if self.version < 1:
            raise DomainInvariantError("Workspace configuration version must be positive")
        if isinstance(self.rag_top_k, bool) or not isinstance(self.rag_top_k, int):
            raise DomainInvariantError("rag_top_k must be an integer between 1 and 64")
        if not 1 <= self.rag_top_k <= 64:
            raise DomainInvariantError("rag_top_k must be between 1 and 64")
        if isinstance(self.llm_temperature, bool) or not isinstance(
            self.llm_temperature, (int, float)
        ):
            raise DomainInvariantError("llm_temperature must be between 0 and 2")
        if not 0.0 <= float(self.llm_temperature) <= 2.0:
            raise DomainInvariantError("llm_temperature must be between 0 and 2")
        object.__setattr__(self, "llm_temperature", float(self.llm_temperature))
        validate_timestamps(self.created_at, self.updated_at)

    def update(
        self,
        patch: WorkspaceConfigurationPatch,
        *,
        actor: ActorReference,
        at: datetime | None = None,
    ) -> WorkspaceConfiguration:
        return replace(
            self,
            rag_top_k=(
                self.rag_top_k if patch.rag_top_k is None else patch.rag_top_k
            ),
            llm_temperature=(
                self.llm_temperature
                if patch.llm_temperature is None
                else patch.llm_temperature
            ),
            version=self.version + 1,
            updated_by=actor,
            updated_at=at or utc_now(),
        )


@dataclass(frozen=True, slots=True)
class WorkspaceConfigurationPatch:
    rag_top_k: int | None = None
    llm_temperature: float | None = None

    def __post_init__(self) -> None:
        if self.rag_top_k is None and self.llm_temperature is None:
            raise DomainInvariantError("Workspace configuration patch cannot be empty")
        if self.rag_top_k is not None and (
            isinstance(self.rag_top_k, bool) or not 1 <= self.rag_top_k <= 64
        ):
            raise DomainInvariantError("rag_top_k must be an integer between 1 and 64")
        if self.llm_temperature is not None and (
            isinstance(self.llm_temperature, bool)
            or not isinstance(self.llm_temperature, (int, float))
            or not 0.0 <= float(self.llm_temperature) <= 2.0
        ):
            raise DomainInvariantError("llm_temperature must be between 0 and 2")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> WorkspaceConfigurationPatch:
        unknown = set(raw) - WORKSPACE_CONFIG_KEYS
        if unknown:
            raise DomainInvariantError(
                "Unknown workspace configuration keys: "
                + ", ".join(sorted(str(key) for key in unknown))
            )
        rag_top_k = raw.get("rag_top_k")
        llm_temperature = raw.get("llm_temperature")
        if rag_top_k is not None and not isinstance(rag_top_k, int):
            raise DomainInvariantError("rag_top_k must be an integer between 1 and 64")
        return cls(
            rag_top_k=rag_top_k,
            llm_temperature=llm_temperature,
        )
