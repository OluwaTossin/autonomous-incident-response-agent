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
    retention: RetentionMarker = RetentionMarker()

    def __post_init__(self) -> None:
        if not self.category.strip() or not self.unit.strip():
            raise DomainInvariantError("Usage category and unit cannot be blank")
        if not math.isfinite(self.quantity) or self.quantity < 0:
            raise DomainInvariantError("Usage quantity must be finite and non-negative")
        require_aware(self.occurred_at, "occurred_at")
        if self.idempotency_key is not None and not self.idempotency_key.strip():
            raise DomainInvariantError("Usage idempotency_key cannot be blank")


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
