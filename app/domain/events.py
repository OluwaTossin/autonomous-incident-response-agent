"""Immutable hosted usage and audit events."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from app.domain.common import (
    ActorReference,
    CorrelationContext,
    DataClassification,
    DomainInvariantError,
    OrganizationScope,
    RetentionMarker,
    WorkspaceScope,
    require_aware,
)
from app.domain.identifiers import AuditEventId, UsageEventId
from app.domain.usage import USAGE_UNITS, UsageType, UsageUnit


@dataclass(frozen=True, slots=True)
class UsageEvent:
    id: UsageEventId
    scope: WorkspaceScope
    category: str
    quantity: float
    unit: str
    occurred_at: datetime
    correlation: CorrelationContext
    actor: ActorReference | None = None
    idempotency_key: str | None = None
    source: str = "application"
    source_reference: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    retention: RetentionMarker = RetentionMarker()

    def __post_init__(self) -> None:
        try:
            usage_type = UsageType(self.category)
            unit = UsageUnit(self.unit)
        except ValueError as exc:
            raise DomainInvariantError("Usage type and unit must be allowlisted") from exc
        if USAGE_UNITS[usage_type] is not unit:
            raise DomainInvariantError("Usage unit does not match usage type")
        if not math.isfinite(self.quantity) or self.quantity < 0:
            raise DomainInvariantError("Usage quantity must be finite and non-negative")
        if self.quantity != int(self.quantity):
            raise DomainInvariantError("Usage quantity must be an integer")
        require_aware(self.occurred_at, "occurred_at")
        if self.idempotency_key is not None and not self.idempotency_key.strip():
            raise DomainInvariantError("Usage idempotency_key cannot be blank")
        source = self.source.strip()
        if not source or len(source) > 80:
            raise DomainInvariantError("Usage source is invalid")
        object.__setattr__(self, "source", source)
        for name in ("source_reference", "resource_type", "resource_id"):
            value = getattr(self, name)
            if value is not None and (not value.strip() or len(value) > 255):
                raise DomainInvariantError(f"Usage {name} is invalid")


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: AuditEventId
    organization_scope: OrganizationScope
    event_type: str
    target_type: str
    target_id: str
    actor: ActorReference
    occurred_at: datetime
    correlation: CorrelationContext
    workspace_scope: WorkspaceScope | None = None
    classification: DataClassification = DataClassification.CONFIDENTIAL
    retention: RetentionMarker = RetentionMarker()
    details: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.event_type.strip() or not self.target_type.strip() or not self.target_id.strip():
            raise DomainInvariantError("Audit event type and target cannot be blank")
        require_aware(self.occurred_at, "occurred_at")
        if (
            self.workspace_scope is not None
            and self.workspace_scope.organization_id != self.organization_scope.organization_id
        ):
            raise DomainInvariantError("Audit workspace must belong to the audit organization")
