"""Narrow source, index, and retrieval contracts shared by AIRA runtimes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from collections.abc import Sequence
from typing import Protocol

from app.domain.common import DomainInvariantError, WorkspaceScope
from app.domain.identifiers import (
    DocumentId,
    DocumentVersionId,
    KnowledgeIndexVersionId,
)
from app.domain.knowledge import DocumentCategory


class KnowledgeSourceOrigin(StrEnum):
    TENANT = "tenant"
    SYSTEM = "system"
    SELF_HOSTED = "self_hosted"


class KnowledgeIndexHandle(Protocol):
    format_version: str


class RetrievalResult(Protocol):
    score: float
    text: str
    source: str
    doc_type: str
    chunk_index: int


@dataclass(frozen=True, slots=True)
class LocalFaissIndexHandle:
    """Filesystem artifact handle used only by the self-hosted adapter."""

    index_dir: Path
    format_version: str = "aira-faiss-local-v1"

    def __post_init__(self) -> None:
        if not str(self.index_dir):
            raise DomainInvariantError("Local FAISS index directory cannot be blank")
        if not self.format_version.strip():
            raise DomainInvariantError("Knowledge index format version cannot be blank")


@dataclass(frozen=True, slots=True)
class HostedKnowledgeIndexReference:
    """Authorized hosted index identity, with no artifact key or cache path."""

    scope: WorkspaceScope
    index_version_id: KnowledgeIndexVersionId
    source_document_versions: tuple[DocumentVersionId, ...]
    format_version: str = "aira-faiss-v1"

    def __post_init__(self) -> None:
        if not self.format_version.strip():
            raise DomainInvariantError("Knowledge index format version cannot be blank")
        if len(set(self.source_document_versions)) != len(
            self.source_document_versions
        ):
            raise DomainInvariantError(
                "Knowledge index source document versions must be unique"
            )


@dataclass(frozen=True, slots=True)
class KnowledgeSourceReference:
    """Attributable source metadata; object locations and contents are excluded."""

    origin: KnowledgeSourceOrigin
    source: str
    category: str
    scope: WorkspaceScope | None = None
    document_id: DocumentId | None = None
    document_version_id: DocumentVersionId | None = None
    checksum_sha256: str | None = None
    size_bytes: int | None = None
    media_type: str | None = None
    system_source_id: str | None = None

    def __post_init__(self) -> None:
        if not self.source.strip() or not self.category.strip():
            raise DomainInvariantError("Knowledge source and category cannot be blank")
        tenant_fields = (
            self.scope,
            self.document_id,
            self.document_version_id,
            self.checksum_sha256,
            self.size_bytes,
            self.media_type,
        )
        if self.origin is KnowledgeSourceOrigin.TENANT:
            if any(value is None for value in tenant_fields):
                raise DomainInvariantError(
                    "Tenant knowledge sources require verified document provenance"
                )
            if self.system_source_id is not None:
                raise DomainInvariantError(
                    "Tenant knowledge sources cannot carry a system source ID"
                )
            checksum = str(self.checksum_sha256)
            if len(checksum) != 64 or any(
                character not in "0123456789abcdef" for character in checksum
            ):
                raise DomainInvariantError(
                    "Tenant knowledge sources require a verified SHA-256 checksum"
                )
            if self.size_bytes is not None and self.size_bytes < 0:
                raise DomainInvariantError(
                    "Tenant knowledge source size cannot be negative"
                )
            if self.media_type is not None and not self.media_type.strip():
                raise DomainInvariantError(
                    "Tenant knowledge source media type cannot be blank"
                )
        elif self.origin is KnowledgeSourceOrigin.SYSTEM:
            if not self.system_source_id or not self.system_source_id.strip():
                raise DomainInvariantError(
                    "System knowledge sources require an explicit source ID"
                )
            if any(value is not None for value in tenant_fields):
                raise DomainInvariantError(
                    "System knowledge sources cannot impersonate tenant documents"
                )
        elif any(
            value is not None for value in (*tenant_fields, self.system_source_id)
        ):
            raise DomainInvariantError(
                "Self-hosted sources use their existing filesystem provenance only"
            )


@dataclass(frozen=True, slots=True)
class KnowledgeSourceSelection:
    tenant_sources: tuple[KnowledgeSourceReference, ...]
    system_sources: tuple[KnowledgeSourceReference, ...] = ()

    def __post_init__(self) -> None:
        if any(
            source.origin is not KnowledgeSourceOrigin.TENANT
            for source in self.tenant_sources
        ):
            raise DomainInvariantError("Tenant source selection contains another origin")
        if any(
            source.origin is not KnowledgeSourceOrigin.SYSTEM
            for source in self.system_sources
        ):
            raise DomainInvariantError("System source selection contains another origin")

    @property
    def all_sources(self) -> tuple[KnowledgeSourceReference, ...]:
        return self.tenant_sources + self.system_sources


@dataclass(frozen=True, slots=True)
class SystemCorpusPolicy:
    """Explicit hosted policy; disabled never contributes repository content."""

    enabled: bool = False
    sources: tuple[KnowledgeSourceReference, ...] = ()

    def __post_init__(self) -> None:
        if any(
            source.origin is not KnowledgeSourceOrigin.SYSTEM for source in self.sources
        ):
            raise DomainInvariantError(
                "System corpus policy accepts only explicit system sources"
            )

    def selected_sources(self) -> tuple[KnowledgeSourceReference, ...]:
        return self.sources if self.enabled else ()


class Retriever(Protocol):
    def retrieve(
        self,
        index: KnowledgeIndexHandle,
        query: str,
        *,
        top_k: int,
    ) -> Sequence[RetrievalResult]: ...


@dataclass(frozen=True, slots=True)
class RetrievalContext:
    index: KnowledgeIndexHandle
    retriever: Retriever
    top_k: int

    def __post_init__(self) -> None:
        if not 1 <= self.top_k <= 64:
            raise DomainInvariantError("Retrieval top_k must be between 1 and 64")


INDEXABLE_DOCUMENT_CATEGORIES = frozenset(
    {
        DocumentCategory.RUNBOOK,
        DocumentCategory.INCIDENT,
        DocumentCategory.LOG,
        DocumentCategory.KNOWLEDGE,
    }
)
