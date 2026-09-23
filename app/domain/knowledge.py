"""Hosted document and knowledge-index domain models."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from app.domain.common import (
    ActorReference,
    DataClassification,
    DomainInvariantError,
    RetentionMarker,
    WorkspaceScope,
    require_aware,
    require_transition,
    utc_now,
    validate_timestamps,
)
from app.domain.identifiers import (
    DocumentId,
    DocumentVersionId,
    KnowledgeIndexVersionId,
)


class DocumentCategory(StrEnum):
    RUNBOOK = "runbook"
    INCIDENT = "incident"
    LOG = "log"
    KNOWLEDGE = "knowledge"
    OTHER = "other"


class DocumentState(StrEnum):
    PENDING_UPLOAD = "pending_upload"
    AVAILABLE = "available"
    FAILED = "failed"
    ARCHIVED = "archived"


class KnowledgeIndexState(StrEnum):
    BUILDING = "building"
    ACTIVE = "active"
    FAILED = "failed"
    INACTIVE = "inactive"


_DOCUMENT_TRANSITIONS = {
    DocumentState.PENDING_UPLOAD: frozenset(
        {DocumentState.AVAILABLE, DocumentState.FAILED, DocumentState.ARCHIVED}
    ),
    DocumentState.AVAILABLE: frozenset({DocumentState.ARCHIVED}),
    DocumentState.FAILED: frozenset(),
    DocumentState.ARCHIVED: frozenset(),
}

_INDEX_TRANSITIONS = {
    KnowledgeIndexState.BUILDING: frozenset(
        {KnowledgeIndexState.ACTIVE, KnowledgeIndexState.FAILED, KnowledgeIndexState.INACTIVE}
    ),
    KnowledgeIndexState.ACTIVE: frozenset({KnowledgeIndexState.INACTIVE}),
    KnowledgeIndexState.FAILED: frozenset(),
    KnowledgeIndexState.INACTIVE: frozenset(),
}

DOCUMENT_TERMINAL_STATES = frozenset({DocumentState.FAILED, DocumentState.ARCHIVED})
KNOWLEDGE_INDEX_TERMINAL_STATES = frozenset(
    {KnowledgeIndexState.FAILED, KnowledgeIndexState.INACTIVE}
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class DocumentReference:
    id: DocumentId
    scope: WorkspaceScope


@dataclass(frozen=True, slots=True)
class Document:
    id: DocumentId
    scope: WorkspaceScope
    name: str
    category: DocumentCategory
    state: DocumentState
    created_by: ActorReference
    created_at: datetime
    updated_at: datetime
    classification: DataClassification = DataClassification.CONFIDENTIAL
    retention: RetentionMarker = RetentionMarker()
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise DomainInvariantError("Document name cannot be blank")
        validate_timestamps(self.created_at, self.updated_at)
        if self.state is DocumentState.FAILED and not self.failure_reason:
            raise DomainInvariantError("Failed documents require failure_reason")
        if self.state is not DocumentState.FAILED and self.failure_reason is not None:
            raise DomainInvariantError("Only failed documents may carry failure_reason")

    @property
    def reference(self) -> DocumentReference:
        return DocumentReference(self.id, self.scope)

    def mark_available(self, *, at: datetime | None = None) -> Document:
        return self._transition(DocumentState.AVAILABLE, at=at)

    def fail(self, reason: str, *, at: datetime | None = None) -> Document:
        normalized = reason.strip()
        if not normalized:
            raise DomainInvariantError("Document failure reason cannot be blank")
        return self._transition(DocumentState.FAILED, at=at, failure_reason=normalized)

    def archive(self, *, at: datetime | None = None) -> Document:
        return self._transition(DocumentState.ARCHIVED, at=at)

    def _transition(
        self,
        target: DocumentState,
        *,
        at: datetime | None,
        failure_reason: str | None = None,
    ) -> Document:
        require_transition("Document", self.state, target, _DOCUMENT_TRANSITIONS)
        return replace(
            self,
            state=target,
            failure_reason=failure_reason,
            updated_at=at or utc_now(),
        )


@dataclass(frozen=True, slots=True)
class DocumentVersion:
    id: DocumentVersionId
    scope: WorkspaceScope
    document: DocumentReference
    version_number: int
    checksum_sha256: str
    size_bytes: int
    media_type: str
    created_by: ActorReference
    created_at: datetime

    def __post_init__(self) -> None:
        if self.scope != self.document.scope:
            raise DomainInvariantError("DocumentVersion and Document must have the same scope")
        if self.version_number < 1:
            raise DomainInvariantError("Document version_number must be positive")
        if not _SHA256_RE.fullmatch(self.checksum_sha256):
            raise DomainInvariantError("Document checksum_sha256 must be 64 lowercase hex characters")
        if self.size_bytes < 0:
            raise DomainInvariantError("Document size_bytes cannot be negative")
        if not self.media_type.strip():
            raise DomainInvariantError("Document media_type cannot be blank")
        require_aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class KnowledgeIndexVersion:
    id: KnowledgeIndexVersionId
    scope: WorkspaceScope
    state: KnowledgeIndexState
    source_document_versions: tuple[DocumentVersionId, ...]
    created_by: ActorReference
    created_at: datetime
    updated_at: datetime
    activated_at: datetime | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        validate_timestamps(self.created_at, self.updated_at)
        if self.activated_at is not None:
            require_aware(self.activated_at, "activated_at")
            if self.activated_at < self.created_at:
                raise DomainInvariantError("Knowledge index activated_at cannot precede created_at")
        if len(set(self.source_document_versions)) != len(self.source_document_versions):
            raise DomainInvariantError("Knowledge index source document versions must be unique")
        if self.state is KnowledgeIndexState.ACTIVE and self.activated_at is None:
            raise DomainInvariantError("Active knowledge indexes require activated_at")
        if self.state is not KnowledgeIndexState.ACTIVE and self.activated_at is not None:
            raise DomainInvariantError("Only active knowledge indexes may carry activated_at")
        if self.state is KnowledgeIndexState.FAILED and not self.failure_reason:
            raise DomainInvariantError("Failed knowledge indexes require failure_reason")
        if self.state is not KnowledgeIndexState.FAILED and self.failure_reason is not None:
            raise DomainInvariantError("Only failed knowledge indexes may carry failure_reason")

    def activate(self, *, at: datetime | None = None) -> KnowledgeIndexVersion:
        target = KnowledgeIndexState.ACTIVE
        require_transition("KnowledgeIndexVersion", self.state, target, _INDEX_TRANSITIONS)
        when = at or utc_now()
        return replace(self, state=target, activated_at=when, updated_at=when)

    def fail(self, reason: str, *, at: datetime | None = None) -> KnowledgeIndexVersion:
        target = KnowledgeIndexState.FAILED
        require_transition("KnowledgeIndexVersion", self.state, target, _INDEX_TRANSITIONS)
        normalized = reason.strip()
        if not normalized:
            raise DomainInvariantError("Knowledge index failure reason cannot be blank")
        when = at or utc_now()
        return replace(self, state=target, failure_reason=normalized, updated_at=when)

    def deactivate(self, *, at: datetime | None = None) -> KnowledgeIndexVersion:
        target = KnowledgeIndexState.INACTIVE
        require_transition("KnowledgeIndexVersion", self.state, target, _INDEX_TRANSITIONS)
        return replace(
            self,
            state=target,
            activated_at=None,
            updated_at=at or utc_now(),
        )
