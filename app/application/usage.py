"""Transport-neutral hosted usage accounting and quota admission contracts."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, Self

from app.auth.context import ActorContext
from app.authorization.permissions import Permission
from app.authorization.service import AuthorizationService, AuthorizedTenantContext
from app.domain.common import CorrelationContext
from app.domain.identifiers import OrganizationId, WorkspaceId
from app.domain.usage import QuotaDecision, QuotaType, UsageType


class UsageQuotaRepository(Protocol):
    def decision(self, quota_type: QuotaType, requested: int, *, at: datetime) -> QuotaDecision: ...
    def record(
        self,
        usage_type: UsageType,
        quantity: int,
        *,
        source: str,
        source_reference: str,
        correlation: CorrelationContext,
        actor,
        at: datetime,
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> bool: ...
    def summary(self, *, at: datetime) -> Sequence[QuotaDecision]: ...
    def reconcile(self, usage_type: UsageType, authoritative_quantity: int, *, at: datetime) -> bool: ...


class UsageUnitOfWork(Protocol):
    usage: UsageQuotaRepository
    def __enter__(self) -> Self: ...
    def __exit__(self, exc_type, exc_value, traceback) -> None: ...


@dataclass(frozen=True, slots=True)
class UsageSummary:
    organization_id: OrganizationId
    workspace_id: WorkspaceId
    generated_at: datetime
    quotas: tuple[QuotaDecision, ...]


class UsageQuotaObserver(Protocol):
    def record(self, event: str, quota_type: str, operation: str, result: str) -> None: ...


class NoopUsageQuotaObserver:
    def record(self, event: str, quota_type: str, operation: str, result: str) -> None:
        return None


class HostedUsageService:
    def __init__(
        self,
        authorization: AuthorizationService,
        uow_factory: Callable[[AuthorizedTenantContext], UsageUnitOfWork],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._authorization = authorization
        self._uow_factory = uow_factory
        self._clock = clock

    def workspace_summary(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
    ) -> UsageSummary:
        context = self._authorization.authorize(
            actor, organization_id, Permission.USAGE_READ, workspace_id=workspace_id
        )
        now = self._clock()
        with self._uow_factory(context) as uow:
            quotas = tuple(uow.usage.summary(at=now))
        return UsageSummary(organization_id, workspace_id, now, quotas)
