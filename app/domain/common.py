"""Shared hosted-domain value objects and invariant helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TypeVar

from app.domain.identifiers import (
    CorrelationId,
    IncidentId,
    JobId,
    OrganizationId,
    ServiceAccountId,
    TriageRunId,
    UserId,
    WorkspaceId,
)


class DomainInvariantError(ValueError):
    """Raised when a hosted-domain invariant would be violated."""


class InvalidStateTransition(DomainInvariantError):
    """Raised when an entity attempts a transition outside its state machine."""


class ActorKind(StrEnum):
    HUMAN = "human"
    SERVICE_ACCOUNT = "service_account"
    SYSTEM = "system"


class DataClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


@dataclass(frozen=True, slots=True)
class ActorReference:
    kind: ActorKind
    actor_id: UserId | ServiceAccountId | None = None
    system_name: str | None = None

    def __post_init__(self) -> None:
        if self.kind is ActorKind.HUMAN and not isinstance(self.actor_id, UserId):
            raise DomainInvariantError("Human actors require a UserId")
        if self.kind is ActorKind.SERVICE_ACCOUNT and not isinstance(
            self.actor_id, ServiceAccountId
        ):
            raise DomainInvariantError("Service-account actors require a ServiceAccountId")
        if self.kind is ActorKind.SYSTEM:
            if self.actor_id is not None:
                raise DomainInvariantError("System actors cannot carry a user or service-account ID")
            if not self.system_name or not self.system_name.strip():
                raise DomainInvariantError("System actors require a non-empty system_name")
            object.__setattr__(self, "system_name", self.system_name.strip())
        elif self.system_name is not None:
            raise DomainInvariantError("Only system actors may carry system_name")


@dataclass(frozen=True, slots=True)
class OrganizationScope:
    organization_id: OrganizationId


@dataclass(frozen=True, slots=True)
class WorkspaceScope:
    organization_id: OrganizationId
    workspace_id: WorkspaceId


@dataclass(frozen=True, slots=True)
class CorrelationContext:
    correlation_id: CorrelationId
    incident_id: IncidentId | None = None
    triage_run_id: TriageRunId | None = None
    job_id: JobId | None = None


@dataclass(frozen=True, slots=True)
class RetentionMarker:
    policy_ref: str | None = None
    retain_until: datetime | None = None

    def __post_init__(self) -> None:
        if self.policy_ref is not None:
            normalized = self.policy_ref.strip()
            if not normalized:
                raise DomainInvariantError("retention policy_ref cannot be blank")
            object.__setattr__(self, "policy_ref", normalized)
        if self.retain_until is not None:
            require_aware(self.retain_until, "retain_until")


def utc_now() -> datetime:
    return datetime.now(UTC)


def require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainInvariantError(f"{field_name} must be timezone-aware")


def validate_timestamps(created_at: datetime, updated_at: datetime) -> None:
    require_aware(created_at, "created_at")
    require_aware(updated_at, "updated_at")
    if updated_at < created_at:
        raise DomainInvariantError("updated_at cannot precede created_at")


StateT = TypeVar("StateT", bound=StrEnum)


def require_transition(
    entity_name: str,
    current: StateT,
    target: StateT,
    allowed: dict[StateT, frozenset[StateT]],
) -> None:
    if target not in allowed.get(current, frozenset()):
        raise InvalidStateTransition(
            f"{entity_name} cannot transition from {current.value} to {target.value}"
        )
