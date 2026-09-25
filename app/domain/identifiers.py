"""Opaque, storage-independent identifiers for the hosted domain."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class DomainId:
    """Canonical non-nil UUID suitable for APIs, URLs, logs, and queues."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError(f"{type(self).__name__} must be constructed from a string")
        try:
            parsed = UUID(self.value)
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"Invalid {type(self).__name__}: {self.value!r}") from exc
        if parsed.int == 0:
            raise ValueError(f"{type(self).__name__} cannot be the nil UUID")
        object.__setattr__(self, "value", str(parsed))

    @classmethod
    def new(cls) -> Self:
        return cls(str(uuid4()))

    @classmethod
    def parse(cls, value: str) -> Self:
        return cls(value)

    def __str__(self) -> str:
        return self.value


class UserId(DomainId):
    pass


class OrganizationId(DomainId):
    pass


class MembershipId(DomainId):
    pass


class WorkspaceId(DomainId):
    pass


class IncidentId(DomainId):
    pass


class TriageRunId(DomainId):
    """Hosted identifier whose string value is the compatible legacy ``triage_id``."""

    @classmethod
    def from_legacy_triage_id(cls, triage_id: str) -> Self:
        return cls.parse(triage_id)

    def to_legacy_triage_id(self) -> str:
        return self.value


class EvidenceId(DomainId):
    pass


class FeedbackId(DomainId):
    pass


class DocumentId(DomainId):
    pass


class DocumentVersionId(DomainId):
    pass


class KnowledgeIndexVersionId(DomainId):
    pass


class IntegrationId(DomainId):
    pass


class AlertReceiptId(DomainId):
    pass


class AwsAlarmStateId(DomainId):
    pass


class JobId(DomainId):
    pass


class ActionId(DomainId):
    pass


class ApprovalId(DomainId):
    pass


class ServiceAccountId(DomainId):
    pass


class ServiceAccountCredentialId(DomainId):
    pass


class MembershipWorkspaceGrantId(DomainId):
    pass


class ServiceAccountGrantId(DomainId):
    pass


class ServiceAccountWorkspaceGrantId(DomainId):
    pass


class AuditEventId(DomainId):
    pass


class UsageEventId(DomainId):
    pass


class CorrelationId(DomainId):
    pass
