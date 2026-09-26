"""Typed operational usage and quota policy values for hosted AIRA."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from app.domain.common import DomainInvariantError, require_aware


class UsageType(StrEnum):
    INCIDENT_CREATED = "incident_created"
    TRIAGE_REQUESTED = "triage_requested"
    TRIAGE_COMPLETED = "triage_completed"
    JOB_CREATED = "job_created"
    DOCUMENT_BYTES_STORED = "document_bytes_stored"
    DOCUMENT_VERSION_CREATED = "document_version_created"
    KNOWLEDGE_INDEX_BUILD = "knowledge_index_build"
    KNOWLEDGE_BUNDLE_BYTES = "knowledge_bundle_bytes"
    AWS_INTEGRATION_COUNT = "aws_integration_count"
    ALERT_EVENT_ACCEPTED = "alert_event_accepted"
    CONTEXT_LOG_BYTES = "context_log_bytes"
    CONTEXT_METRIC_POINTS = "context_metric_points"
    ACTION_PROPOSAL_CREATED = "action_proposal_created"
    APPROVAL_REQUESTED = "approval_requested"
    EXECUTION_INTENT_PREPARED = "execution_intent_prepared"
    LLM_INPUT_TOKENS = "llm_input_tokens"
    LLM_OUTPUT_TOKENS = "llm_output_tokens"


class UsageUnit(StrEnum):
    EVENT = "event"
    BYTE = "byte"
    TOKEN = "token"
    ITEM = "item"


USAGE_UNITS = {
    UsageType.INCIDENT_CREATED: UsageUnit.EVENT,
    UsageType.TRIAGE_REQUESTED: UsageUnit.EVENT,
    UsageType.TRIAGE_COMPLETED: UsageUnit.EVENT,
    UsageType.JOB_CREATED: UsageUnit.EVENT,
    UsageType.DOCUMENT_BYTES_STORED: UsageUnit.BYTE,
    UsageType.DOCUMENT_VERSION_CREATED: UsageUnit.EVENT,
    UsageType.KNOWLEDGE_INDEX_BUILD: UsageUnit.EVENT,
    UsageType.KNOWLEDGE_BUNDLE_BYTES: UsageUnit.BYTE,
    UsageType.AWS_INTEGRATION_COUNT: UsageUnit.ITEM,
    UsageType.ALERT_EVENT_ACCEPTED: UsageUnit.EVENT,
    UsageType.CONTEXT_LOG_BYTES: UsageUnit.BYTE,
    UsageType.CONTEXT_METRIC_POINTS: UsageUnit.ITEM,
    UsageType.ACTION_PROPOSAL_CREATED: UsageUnit.EVENT,
    UsageType.APPROVAL_REQUESTED: UsageUnit.EVENT,
    UsageType.EXECUTION_INTENT_PREPARED: UsageUnit.EVENT,
    UsageType.LLM_INPUT_TOKENS: UsageUnit.TOKEN,
    UsageType.LLM_OUTPUT_TOKENS: UsageUnit.TOKEN,
}


class QuotaType(StrEnum):
    TRIAGE_REQUESTS_PER_HOUR = "triage_requests_per_hour"
    CONCURRENT_TRIAGE_RUNS = "concurrent_triage_runs"
    DOCUMENT_COUNT = "document_count"
    DOCUMENT_BYTES = "document_bytes"
    ACTIVE_AWS_INTEGRATIONS = "active_aws_integrations"
    ALERT_EVENTS_PER_HOUR = "alert_events_per_hour"
    CONCURRENT_INDEX_BUILDS = "concurrent_index_builds"
    EXECUTION_INTENTS_PER_HOUR = "execution_intents_per_hour"


class QuotaWindow(StrEnum):
    LIFETIME = "lifetime"
    UTC_HOUR = "utc_hour"
    CONCURRENT = "concurrent"


class QuotaStatus(StrEnum):
    ALLOWED = "allowed"
    WARNING = "warning"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class QuotaLimit:
    quota_type: QuotaType
    hard_limit: int
    warning_percent: int = 80
    window: QuotaWindow = QuotaWindow.LIFETIME
    policy_version: int = 1

    def __post_init__(self) -> None:
        if self.hard_limit <= 0:
            raise DomainInvariantError("Quota hard limit must be positive")
        if not 1 <= self.warning_percent <= 100:
            raise DomainInvariantError("Quota warning percent must be between 1 and 100")
        if self.policy_version <= 0:
            raise DomainInvariantError("Quota policy version must be positive")

    @property
    def warning_threshold(self) -> int:
        return max(1, (self.hard_limit * self.warning_percent + 99) // 100)


@dataclass(frozen=True, slots=True)
class QuotaDecision:
    status: QuotaStatus
    quota_type: QuotaType
    current: int
    requested: int
    limit: int
    remaining: int
    policy_version: int
    reset_at: datetime | None = None

    def __post_init__(self) -> None:
        if min(self.current, self.requested, self.limit, self.remaining) < 0:
            raise DomainInvariantError("Quota decision quantities cannot be negative")
        if self.reset_at is not None:
            require_aware(self.reset_at, "reset_at")


class QuotaExceeded(RuntimeError):
    """Stable transport-neutral hard-limit rejection."""

    def __init__(self, decision: QuotaDecision) -> None:
        self.decision = decision
        super().__init__(f"Quota exceeded: {decision.quota_type.value}")


class UsageSourceConflict(RuntimeError):
    """An idempotency identity was replayed with different accounting data."""


def quota_window(at: datetime, window: QuotaWindow) -> tuple[datetime, datetime | None]:
    require_aware(at, "at")
    normalized = at.astimezone(UTC)
    if window is QuotaWindow.UTC_HOUR:
        start = normalized.replace(minute=0, second=0, microsecond=0)
        return start, start + timedelta(hours=1)
    return datetime(1970, 1, 1, tzinfo=UTC), None
