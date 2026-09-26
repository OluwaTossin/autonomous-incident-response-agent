"""PostgreSQL-authoritative usage ledger, counters, and quota decisions."""

from __future__ import annotations

from datetime import datetime
from types import TracebackType
from uuid import UUID

from sqlalchemy import case, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.authorization.service import AuthorizedTenantContext
from app.domain.common import CorrelationContext, WorkspaceScope
from app.domain.events import UsageEvent
from app.domain.identifiers import UsageEventId
from app.domain.usage import (
    QuotaDecision,
    QuotaExceeded,
    QuotaLimit,
    QuotaStatus,
    QuotaType,
    QuotaWindow,
    UsageType,
    UsageSourceConflict,
    USAGE_UNITS,
    quota_window,
)
from app.persistence.postgres.mappers import usage_event_to_record
from app.persistence.postgres.models import (
    AwsIntegrationRecord,
    DocumentRecord,
    DocumentVersionRecord,
    JobRecord,
    KnowledgeIndexVersionRecord,
    QuotaPolicyRecord,
    UsageCounterRecord,
    UsageEventRecord,
)
from app.persistence.postgres.tenant import TenantContext, apply_tenant_context


DEFAULT_QUOTAS: dict[QuotaType, QuotaLimit] = {
    QuotaType.TRIAGE_REQUESTS_PER_HOUR: QuotaLimit(QuotaType.TRIAGE_REQUESTS_PER_HOUR, 100, window=QuotaWindow.UTC_HOUR),
    QuotaType.CONCURRENT_TRIAGE_RUNS: QuotaLimit(QuotaType.CONCURRENT_TRIAGE_RUNS, 4, window=QuotaWindow.CONCURRENT),
    QuotaType.DOCUMENT_COUNT: QuotaLimit(QuotaType.DOCUMENT_COUNT, 1000),
    QuotaType.DOCUMENT_BYTES: QuotaLimit(QuotaType.DOCUMENT_BYTES, 5 * 1024 * 1024 * 1024),
    QuotaType.ACTIVE_AWS_INTEGRATIONS: QuotaLimit(QuotaType.ACTIVE_AWS_INTEGRATIONS, 20),
    QuotaType.ALERT_EVENTS_PER_HOUR: QuotaLimit(QuotaType.ALERT_EVENTS_PER_HOUR, 1000, window=QuotaWindow.UTC_HOUR),
    QuotaType.CONCURRENT_INDEX_BUILDS: QuotaLimit(QuotaType.CONCURRENT_INDEX_BUILDS, 1, window=QuotaWindow.CONCURRENT),
    QuotaType.EXECUTION_INTENTS_PER_HOUR: QuotaLimit(QuotaType.EXECUTION_INTENTS_PER_HOUR, 100, window=QuotaWindow.UTC_HOUR),
}


def quota_defaults_from_settings(settings) -> dict[QuotaType, QuotaLimit]:
    """Resolve deployment-owned defaults without coupling domain policy to Settings."""
    values = dict(DEFAULT_QUOTAS)
    configured = {
        QuotaType.TRIAGE_REQUESTS_PER_HOUR: settings.aira_quota_triage_per_hour,
        QuotaType.CONCURRENT_TRIAGE_RUNS: settings.aira_quota_concurrent_triage,
        QuotaType.DOCUMENT_COUNT: settings.aira_quota_document_count,
        QuotaType.DOCUMENT_BYTES: settings.aira_quota_document_bytes,
        QuotaType.ACTIVE_AWS_INTEGRATIONS: settings.aira_quota_active_aws_integrations,
        QuotaType.ALERT_EVENTS_PER_HOUR: settings.aira_quota_alerts_per_hour,
        QuotaType.CONCURRENT_INDEX_BUILDS: settings.aira_quota_concurrent_index_builds,
        QuotaType.EXECUTION_INTENTS_PER_HOUR: settings.aira_quota_execution_intents_per_hour,
    }
    for quota_type, hard_limit in configured.items():
        current = values[quota_type]
        values[quota_type] = QuotaLimit(
            quota_type,
            hard_limit,
            current.warning_percent,
            current.window,
            current.policy_version,
        )
    return values

_QUOTA_USAGE = {
    QuotaType.TRIAGE_REQUESTS_PER_HOUR: UsageType.TRIAGE_REQUESTED,
    QuotaType.ALERT_EVENTS_PER_HOUR: UsageType.ALERT_EVENT_ACCEPTED,
    QuotaType.EXECUTION_INTENTS_PER_HOUR: UsageType.EXECUTION_INTENT_PREPARED,
}


class PostgresUsageQuotaRepository:
    def __init__(self, session: Session, context: AuthorizedTenantContext, defaults=None, observer=None) -> None:
        if context.workspace_id is None:
            raise ValueError("Usage accounting requires workspace scope")
        self._session = session
        self._context = context
        self._defaults = dict(defaults or DEFAULT_QUOTAS)
        self._observer = observer

    def lock(self, quota_type: QuotaType) -> None:
        key = f"quota:{self._context.organization_id}:{self._context.workspace_id}:{quota_type.value}"
        self._session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})

    def limit(self, quota_type: QuotaType) -> QuotaLimit:
        record = self._session.scalar(
            select(QuotaPolicyRecord)
            .where(QuotaPolicyRecord.quota_type == quota_type.value)
            .order_by(QuotaPolicyRecord.workspace_id.is_not(None).desc())
            .limit(1)
        )
        if record is not None:
            return QuotaLimit(
                quota_type, record.hard_limit, record.warning_percent,
                QuotaWindow(record.window_kind), record.policy_version,
            )
        try:
            return self._defaults[quota_type]
        except KeyError as exc:
            raise RuntimeError(f"No quota policy configured for {quota_type.value}") from exc

    def decision(self, quota_type: QuotaType, requested: int, *, at: datetime) -> QuotaDecision:
        if requested < 0:
            raise ValueError("Requested quota quantity cannot be negative")
        self.lock(quota_type)
        policy = self.limit(quota_type)
        usage_type = _QUOTA_USAGE.get(quota_type)
        current = 0 if usage_type is None else self._counter(usage_type, policy.window, at)
        decision = self.decide(policy, current, requested, at=at)
        self._observe(decision)
        if decision.status is QuotaStatus.REJECTED:
            raise QuotaExceeded(decision)
        return decision

    def admit_current(self, quota_type: QuotaType, current: int, requested: int, *, at: datetime) -> QuotaDecision:
        self.lock(quota_type)
        decision = self.decide(self.limit(quota_type), current, requested, at=at)
        self._observe(decision)
        if decision.status is QuotaStatus.REJECTED:
            raise QuotaExceeded(decision)
        return decision

    def decide(self, policy: QuotaLimit, current: int, requested: int, *, at: datetime) -> QuotaDecision:
        total = current + requested
        status = QuotaStatus.REJECTED if total > policy.hard_limit else (
            QuotaStatus.WARNING if total >= policy.warning_threshold else QuotaStatus.ALLOWED
        )
        _, reset_at = quota_window(at, policy.window)
        decision = QuotaDecision(
            status, policy.quota_type, current, requested, policy.hard_limit,
            max(0, policy.hard_limit - total), policy.policy_version, reset_at,
        )
        return decision

    def record(self, usage_type: UsageType, quantity: int, *, source: str, source_reference: str,
               correlation: CorrelationContext, actor, at: datetime,
               resource_type: str | None = None, resource_id: str | None = None) -> bool:
        if quantity < 0:
            raise ValueError("Usage quantity cannot be negative")
        event = UsageEvent(
            UsageEventId.new(),
            WorkspaceScope(self._context.organization_id, self._context.workspace_id),
            usage_type.value, quantity, USAGE_UNITS[usage_type].value, at, correlation,
            actor=actor, idempotency_key=f"{usage_type.value}:{source}:{source_reference}",
            source=source, source_reference=source_reference,
            resource_type=resource_type, resource_id=resource_id,
        )
        record = usage_event_to_record(event)
        values = {column.name: getattr(record, column.name) for column in UsageEventRecord.__table__.columns}
        inserted = self._session.scalar(
            insert(UsageEventRecord).values(**values).on_conflict_do_nothing(
                index_elements=["organization_id", "workspace_id", "category", "source", "source_reference"],
                index_where=UsageEventRecord.source_reference.is_not(None),
            ).returning(UsageEventRecord.id)
        )
        if inserted is None:
            existing = self._session.scalar(
                select(UsageEventRecord).where(
                    UsageEventRecord.category == usage_type.value,
                    UsageEventRecord.source == source,
                    UsageEventRecord.source_reference == source_reference,
                )
            )
            expected = (
                quantity,
                USAGE_UNITS[usage_type].value,
                resource_type,
                resource_id,
            )
            actual = None if existing is None else (
                existing.quantity,
                existing.unit,
                existing.resource_type,
                existing.resource_id,
            )
            if actual != expected:
                raise UsageSourceConflict(
                    "Usage source identity is already bound to different accounting data"
                )
            return False
        self._increment(usage_type, quantity, at=at)
        return True

    def summary(self, *, at: datetime):
        decisions = []
        for quota_type in sorted(self._defaults, key=lambda item: item.value):
            policy = self.limit(quota_type)
            current = self._current_for_quota(quota_type, policy, at)
            decisions.append(self.decide(policy, current, 0, at=at))
        return decisions

    def _current_for_quota(
        self, quota_type: QuotaType, policy: QuotaLimit, at: datetime
    ) -> int:
        usage_type = _QUOTA_USAGE.get(quota_type)
        if usage_type is not None:
            return self._counter(usage_type, policy.window, at)
        if quota_type is QuotaType.CONCURRENT_TRIAGE_RUNS:
            statement = select(func.count()).select_from(JobRecord).where(
                JobRecord.kind == "triage",
                JobRecord.state.in_(("pending", "running")),
            )
        elif quota_type is QuotaType.DOCUMENT_COUNT:
            statement = select(func.count()).select_from(DocumentRecord).where(
                DocumentRecord.state != "archived"
            )
        elif quota_type is QuotaType.DOCUMENT_BYTES:
            statement = select(
                func.coalesce(
                    func.sum(
                        case(
                            (
                                DocumentVersionRecord.verified_size_bytes.is_not(None),
                                DocumentVersionRecord.verified_size_bytes,
                            ),
                            else_=DocumentVersionRecord.size_bytes,
                        )
                    ),
                    0,
                )
            ).where(DocumentVersionRecord.object_deleted_at.is_(None))
        elif quota_type is QuotaType.ACTIVE_AWS_INTEGRATIONS:
            statement = select(func.count()).select_from(AwsIntegrationRecord).where(
                AwsIntegrationRecord.state != "disabled"
            )
        elif quota_type is QuotaType.CONCURRENT_INDEX_BUILDS:
            statement = select(func.count()).select_from(
                KnowledgeIndexVersionRecord
            ).where(KnowledgeIndexVersionRecord.state == "building")
        else:  # pragma: no cover - all configured quota types are handled above
            raise RuntimeError(f"No usage source configured for {quota_type.value}")
        return int(self._session.scalar(statement) or 0)

    def reconcile(self, usage_type: UsageType, authoritative_quantity: int, *, at: datetime) -> bool:
        if authoritative_quantity < 0:
            raise ValueError("Authoritative usage cannot be negative")
        start, _ = quota_window(at, QuotaWindow.LIFETIME)
        current = self._counter(usage_type, QuotaWindow.LIFETIME, at)
        if current == authoritative_quantity:
            return False
        self._upsert_counter(usage_type, start, 0, authoritative_quantity, at, replace=True)
        return True

    def _counter(self, usage_type: UsageType, window: QuotaWindow, at: datetime) -> int:
        start, _ = quota_window(at, window)
        seconds = 3600 if window is QuotaWindow.UTC_HOUR else 0
        return int(self._session.scalar(
            select(UsageCounterRecord.quantity).where(
                UsageCounterRecord.organization_id == UUID(str(self._context.organization_id)),
                UsageCounterRecord.workspace_id == UUID(str(self._context.workspace_id)),
                UsageCounterRecord.usage_type == usage_type.value,
                UsageCounterRecord.window_start == start,
                UsageCounterRecord.window_seconds == seconds,
            )
        ) or 0)

    def _increment(self, usage_type: UsageType, quantity: int, *, at: datetime) -> None:
        for window, seconds in ((QuotaWindow.LIFETIME, 0), (QuotaWindow.UTC_HOUR, 3600)):
            start, _ = quota_window(at, window)
            self._upsert_counter(usage_type, start, seconds, quantity, at)

    def _upsert_counter(self, usage_type, start, seconds, quantity, at, *, replace=False):
        statement = insert(UsageCounterRecord).values(
            organization_id=UUID(str(self._context.organization_id)),
            workspace_id=UUID(str(self._context.workspace_id)), usage_type=usage_type.value,
            window_start=start, window_seconds=seconds, quantity=quantity, updated_at=at,
        )
        value = statement.excluded.quantity if replace else UsageCounterRecord.quantity + statement.excluded.quantity
        self._session.execute(statement.on_conflict_do_update(
            index_elements=["organization_id", "workspace_id", "usage_type", "window_start", "window_seconds"],
            set_={"quantity": value, "updated_at": at},
        ))

    def _observe(self, decision: QuotaDecision) -> None:
        if self._observer is None or decision.status is QuotaStatus.ALLOWED:
            return
        event = "quota_rejections" if decision.status is QuotaStatus.REJECTED else "quota_warnings"
        self._observer.record(
            event,
            decision.quota_type.value,
            decision.quota_type.value,
            decision.status.value,
        )


class PostgresUsageUnitOfWork:
    def __init__(self, session_factory: sessionmaker[Session], context: AuthorizedTenantContext, defaults=None, observer=None) -> None:
        self._session_factory = session_factory
        self._context = context
        self._defaults = defaults
        self._observer = observer
        self.session: Session | None = None

    def __enter__(self):
        self.session = self._session_factory()
        self.session.begin()
        apply_tenant_context(self.session, TenantContext(self._context.organization_id, self._context.workspace_id))
        self.usage = PostgresUsageQuotaRepository(
            self.session, self._context, self._defaults, self._observer
        )
        return self

    def __exit__(self, exc_type, exc_value, traceback: TracebackType | None) -> None:
        if self.session is None:
            return
        try:
            self.session.commit() if exc_type is None else self.session.rollback()
        finally:
            self.session.close()
            self.session = None
