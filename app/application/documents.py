"""Hosted source-document lifecycle and presigned transfer workflows."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Protocol, Self

from app.auth.context import ActorContext
from app.authorization.permissions import Permission
from app.authorization.service import AuthorizationService, AuthorizedTenantContext
from app.documents.storage import (
    DocumentObjectNotFound,
    DocumentObjectStorage,
    DocumentStorageError,
    PresignedDownload,
    PresignedUpload,
    StoredObjectMetadata,
)
from app.domain.common import CorrelationContext, OrganizationScope, WorkspaceScope
from app.domain.events import AuditEvent
from app.domain.identifiers import (
    AuditEventId,
    CorrelationId,
    DocumentId,
    DocumentVersionId,
    OrganizationId,
    WorkspaceId,
)
from app.domain.knowledge import (
    ContentSafetyState,
    Document,
    DocumentCategory,
    DocumentState,
    DocumentVersion,
    DocumentVersionState,
)

_SAFE_FILENAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,254}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_MEDIA_TYPES = {
    ".md": frozenset({"text/markdown", "text/plain"}),
    ".markdown": frozenset({"text/markdown", "text/plain"}),
    ".txt": frozenset({"text/plain"}),
    ".log": frozenset({"text/plain"}),
    ".yaml": frozenset({"application/yaml", "text/yaml", "text/plain"}),
    ".yml": frozenset({"application/yaml", "text/yaml", "text/plain"}),
}


class DocumentConflict(Exception):
    """The requested document lifecycle operation conflicts with current state."""


class DocumentNotFound(Exception):
    """The authorized document or version does not exist."""


class DocumentValidationError(ValueError):
    """Document metadata does not satisfy the hosted upload policy."""


class DocumentFinalizationError(DocumentConflict):
    """Uploaded object metadata does not match the pending immutable version."""


class DocumentRepository(Protocol):
    def add(self, document: Document) -> None: ...
    def get(self, document_id: DocumentId) -> Document | None: ...
    def list(self, *, include_archived: bool = False) -> Sequence[Document]: ...
    def save(self, document: Document, *, expected_state: DocumentState) -> None: ...


class DocumentVersionRepository(Protocol):
    def add(self, version: DocumentVersion) -> None: ...
    def get(self, version_id: DocumentVersionId) -> DocumentVersion | None: ...
    def list_for_document(self, document_id: DocumentId) -> Sequence[DocumentVersion]: ...
    def next_version_number(self, document_id: DocumentId) -> int: ...
    def save(
        self,
        version: DocumentVersion,
        *,
        expected_state: DocumentVersionState,
    ) -> None: ...


class AuditEventRepository(Protocol):
    def add(self, event: AuditEvent) -> None: ...


class DocumentUnitOfWork(Protocol):
    documents: DocumentRepository
    document_versions: DocumentVersionRepository
    audit_events: AuditEventRepository

    def __enter__(self) -> Self: ...
    def __exit__(self, exc_type, exc_value, traceback) -> None: ...


DocumentUnitOfWorkFactory = Callable[[AuthorizedTenantContext], DocumentUnitOfWork]


@dataclass(frozen=True, slots=True)
class DocumentUploadPolicy:
    max_size_bytes: int = 5_242_880
    upload_ttl_seconds: int = 300
    download_ttl_seconds: int = 300

    def __post_init__(self) -> None:
        if self.max_size_bytes < 1:
            raise ValueError("Document max size must be positive")
        for value in (self.upload_ttl_seconds, self.download_ttl_seconds):
            if not 30 <= value <= 900:
                raise ValueError("Document presign TTL must be between 30 and 900 seconds")


@dataclass(frozen=True, slots=True)
class DocumentVersionMetadata:
    id: DocumentVersionId
    document_id: DocumentId
    version_number: int
    state: DocumentVersionState
    original_filename: str
    checksum_sha256: str
    size_bytes: int
    media_type: str
    content_safety_state: ContentSafetyState
    finalized_at: datetime | None
    failure_reason: str | None
    object_deleted_at: datetime | None


@dataclass(frozen=True, slots=True)
class DocumentUploadIntent:
    document: Document
    version: DocumentVersionMetadata
    upload: PresignedUpload


def document_object_key(
    scope: WorkspaceScope,
    document_id: DocumentId,
    version_id: DocumentVersionId,
) -> str:
    return (
        f"documents/{scope.organization_id}/{scope.workspace_id}/"
        f"{document_id}/{version_id}/source"
    )


class HostedDocumentService:
    def __init__(
        self,
        authorization: AuthorizationService,
        uow_factory: DocumentUnitOfWorkFactory,
        storage: DocumentObjectStorage,
        *,
        policy: DocumentUploadPolicy = DocumentUploadPolicy(),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._authorization = authorization
        self._uow_factory = uow_factory
        self._storage = storage
        self._policy = policy
        self._clock = clock

    def initiate_document_upload(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        *,
        original_filename: str,
        category: DocumentCategory,
        checksum_sha256: str,
        size_bytes: int,
        media_type: str,
        correlation: CorrelationContext | None = None,
    ) -> DocumentUploadIntent:
        correlation = correlation or CorrelationContext(CorrelationId.new())
        filename, checksum, normalized_media_type = self._validate_upload(
            original_filename, checksum_sha256, size_bytes, media_type
        )
        context = self._authorize_manage(actor, organization_id, workspace_id)
        now = self._clock()
        scope = WorkspaceScope(organization_id, workspace_id)
        document = Document(
            id=DocumentId.new(),
            scope=scope,
            name=filename,
            category=category,
            state=DocumentState.PENDING_UPLOAD,
            created_by=actor.actor,
            created_at=now,
            updated_at=now,
        )
        version = self._new_version(
            document,
            actor,
            version_number=1,
            original_filename=filename,
            checksum_sha256=checksum,
            size_bytes=size_bytes,
            media_type=normalized_media_type,
            now=now,
        )
        with self._uow_factory(context) as uow:
            uow.documents.add(document)
            uow.document_versions.add(version)
            upload = self._storage.create_presigned_upload(
                version.object_key,
                size_bytes=version.size_bytes,
                media_type=version.media_type,
                checksum_sha256=version.checksum_sha256,
                ttl_seconds=self._policy.upload_ttl_seconds,
            )
            self._audit(
                uow,
                actor,
                document,
                "document.created",
                correlation,
                version=version,
                details=(("category", document.category.value),),
            )
            self._audit(
                uow,
                actor,
                document,
                "document.version_created",
                correlation,
                version=version,
            )
            self._audit_upload_issued(uow, actor, document, version, correlation)
        return DocumentUploadIntent(document, self._metadata(version), upload)

    def initiate_version_upload(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        document_id: DocumentId,
        *,
        original_filename: str,
        checksum_sha256: str,
        size_bytes: int,
        media_type: str,
        correlation: CorrelationContext | None = None,
    ) -> DocumentUploadIntent:
        correlation = correlation or CorrelationContext(CorrelationId.new())
        filename, checksum, normalized_media_type = self._validate_upload(
            original_filename, checksum_sha256, size_bytes, media_type
        )
        context = self._authorize_manage(actor, organization_id, workspace_id)
        now = self._clock()
        with self._uow_factory(context) as uow:
            document = self._required_document(uow, document_id, context)
            version = self._new_version(
                document,
                actor,
                version_number=uow.document_versions.next_version_number(document_id),
                original_filename=filename,
                checksum_sha256=checksum,
                size_bytes=size_bytes,
                media_type=normalized_media_type,
                now=now,
            )
            uow.document_versions.add(version)
            upload = self._storage.create_presigned_upload(
                version.object_key,
                size_bytes=version.size_bytes,
                media_type=version.media_type,
                checksum_sha256=version.checksum_sha256,
                ttl_seconds=self._policy.upload_ttl_seconds,
            )
            self._audit(
                uow,
                actor,
                document,
                "document.version_created",
                correlation,
                version=version,
            )
            self._audit_upload_issued(uow, actor, document, version, correlation)
        return DocumentUploadIntent(document, self._metadata(version), upload)

    def list_documents(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        *,
        include_archived: bool = False,
    ) -> tuple[Document, ...]:
        context = self._authorize_read(actor, organization_id, workspace_id)
        with self._uow_factory(context) as uow:
            return tuple(uow.documents.list(include_archived=include_archived))

    def get_document(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        document_id: DocumentId,
    ) -> Document:
        context = self._authorize_read(actor, organization_id, workspace_id)
        with self._uow_factory(context) as uow:
            return self._required_document(
                uow, document_id, context, allow_archived=True
            )

    def list_versions(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        document_id: DocumentId,
    ) -> tuple[DocumentVersionMetadata, ...]:
        context = self._authorize_read(actor, organization_id, workspace_id)
        with self._uow_factory(context) as uow:
            self._required_document(uow, document_id, context, allow_archived=True)
            return tuple(
                self._metadata(version)
                for version in uow.document_versions.list_for_document(document_id)
            )

    def finalize_upload(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        document_id: DocumentId,
        version_id: DocumentVersionId,
        *,
        correlation: CorrelationContext | None = None,
    ) -> DocumentVersionMetadata:
        context = self._authorize_manage(actor, organization_id, workspace_id)
        with self._uow_factory(context) as uow:
            document = self._required_document(uow, document_id, context)
            version = self._required_version(uow, document, version_id)
            if version.state is DocumentVersionState.AVAILABLE:
                return self._metadata(version)
            if version.state is not DocumentVersionState.PENDING_UPLOAD:
                raise DocumentConflict("Document version cannot be finalized")
            object_key = version.object_key

        try:
            stored = self._storage.stat(object_key)
        except DocumentObjectNotFound as exc:
            raise DocumentFinalizationError("Uploaded document object is missing") from exc
        except DocumentStorageError:
            raise

        mismatch = self._metadata_mismatch(version, stored)
        if mismatch is not None:
            self._fail_upload(
                actor,
                organization_id,
                workspace_id,
                document_id,
                version_id,
                mismatch,
                correlation,
            )
            raise DocumentFinalizationError(mismatch)

        context = self._authorize_manage(actor, organization_id, workspace_id)
        with self._uow_factory(context) as uow:
            document = self._required_document(uow, document_id, context)
            current = self._required_version(uow, document, version_id)
            if current.state is DocumentVersionState.AVAILABLE:
                return self._metadata(current)
            if current.state is not DocumentVersionState.PENDING_UPLOAD:
                raise DocumentConflict("Document version cannot be finalized")
            finalized = current.finalize(
                checksum_sha256=stored.checksum_sha256 or "",
                size_bytes=stored.size_bytes,
                media_type=stored.media_type,
                at=self._clock(),
            )
            uow.document_versions.save(
                finalized, expected_state=DocumentVersionState.PENDING_UPLOAD
            )
            if document.state is DocumentState.PENDING_UPLOAD:
                available = document.mark_available(at=self._clock())
                uow.documents.save(
                    available, expected_state=DocumentState.PENDING_UPLOAD
                )
                document = available
            self._audit(
                uow,
                actor,
                document,
                "document.upload_finalized",
                correlation,
                version=finalized,
                details=(("size_bytes", str(finalized.verified_size_bytes)),),
            )
            return self._metadata(finalized)

    def issue_download(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        document_id: DocumentId,
        version_id: DocumentVersionId,
        *,
        correlation: CorrelationContext | None = None,
    ) -> PresignedDownload:
        context = self._authorize_read(actor, organization_id, workspace_id)
        with self._uow_factory(context) as uow:
            document = self._required_document(uow, document_id, context)
            version = self._required_version(uow, document, version_id)
            if version.state is not DocumentVersionState.AVAILABLE:
                raise DocumentConflict("Only available document versions can be downloaded")
            download = self._storage.create_presigned_download(
                version.object_key,
                download_filename=version.original_filename,
                ttl_seconds=self._policy.download_ttl_seconds,
            )
            self._audit(
                uow,
                actor,
                document,
                "document.download_issued",
                correlation,
                version=version,
            )
            return download

    def archive_document(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        document_id: DocumentId,
        *,
        correlation: CorrelationContext | None = None,
    ) -> Document:
        context = self._authorize_manage(actor, organization_id, workspace_id)
        with self._uow_factory(context) as uow:
            document = self._required_document(uow, document_id, context)
            archived = document.archive(at=self._clock())
            uow.documents.save(archived, expected_state=document.state)
            self._audit(
                uow,
                actor,
                archived,
                "document.archived",
                correlation,
                details=(("objects_retained", "true"),),
            )
            return archived

    def delete_failed_object(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        document_id: DocumentId,
        version_id: DocumentVersionId,
        *,
        correlation: CorrelationContext | None = None,
    ) -> DocumentVersionMetadata:
        context = self._authorize_manage(actor, organization_id, workspace_id)
        with self._uow_factory(context) as uow:
            document = self._required_document(uow, document_id, context)
            version = self._required_version(uow, document, version_id)
            if version.state is not DocumentVersionState.FAILED:
                raise DocumentConflict("Only failed upload objects can be deleted")
            if version.object_deleted_at is not None:
                return self._metadata(version)
            object_key = version.object_key

        self._storage.delete(object_key)
        context = self._authorize_manage(actor, organization_id, workspace_id)
        with self._uow_factory(context) as uow:
            document = self._required_document(uow, document_id, context)
            current = self._required_version(uow, document, version_id)
            if current.object_deleted_at is not None:
                return self._metadata(current)
            deleted = current.mark_object_deleted(at=self._clock())
            uow.document_versions.save(
                deleted, expected_state=DocumentVersionState.FAILED
            )
            self._audit(
                uow,
                actor,
                document,
                "document.failed_object_deleted",
                correlation,
                version=deleted,
            )
            return self._metadata(deleted)

    def _fail_upload(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        document_id: DocumentId,
        version_id: DocumentVersionId,
        reason: str,
        correlation: CorrelationContext | None,
    ) -> None:
        context = self._authorize_manage(actor, organization_id, workspace_id)
        with self._uow_factory(context) as uow:
            document = self._required_document(uow, document_id, context)
            current = self._required_version(uow, document, version_id)
            if current.state is not DocumentVersionState.PENDING_UPLOAD:
                return
            failed = current.fail(reason, at=self._clock())
            uow.document_versions.save(
                failed, expected_state=DocumentVersionState.PENDING_UPLOAD
            )
            self._audit(
                uow,
                actor,
                document,
                "document.upload_failed",
                correlation,
                version=failed,
                details=(("reason", reason), ("object_cleanup_required", "true")),
            )

    def _new_version(
        self,
        document: Document,
        actor: ActorContext,
        *,
        version_number: int,
        original_filename: str,
        checksum_sha256: str,
        size_bytes: int,
        media_type: str,
        now: datetime,
    ) -> DocumentVersion:
        version_id = DocumentVersionId.new()
        return DocumentVersion(
            id=version_id,
            scope=document.scope,
            document=document.reference,
            version_number=version_number,
            checksum_sha256=checksum_sha256,
            size_bytes=size_bytes,
            media_type=media_type,
            original_filename=original_filename,
            storage_provider="s3",
            object_key=document_object_key(document.scope, document.id, version_id),
            state=DocumentVersionState.PENDING_UPLOAD,
            created_by=actor.actor,
            created_at=now,
            updated_at=now,
        )

    def _validate_upload(
        self,
        original_filename: str,
        checksum_sha256: str,
        size_bytes: int,
        media_type: str,
    ) -> tuple[str, str, str]:
        filename = original_filename.strip()
        if (
            not filename
            or PurePath(filename).name != filename
            or not _SAFE_FILENAME_RE.fullmatch(filename)
        ):
            raise DocumentValidationError("Document filename is invalid")
        suffix = PurePath(filename).suffix.lower()
        normalized_media_type = media_type.strip().lower()
        if normalized_media_type not in _ALLOWED_MEDIA_TYPES.get(suffix, frozenset()):
            raise DocumentValidationError("Document type is unsupported")
        if isinstance(size_bytes, bool) or not isinstance(size_bytes, int):
            raise DocumentValidationError("Document size must be an integer")
        if not 1 <= size_bytes <= self._policy.max_size_bytes:
            raise DocumentValidationError(
                f"Document size must be between 1 and {self._policy.max_size_bytes} bytes"
            )
        checksum = checksum_sha256.strip().lower()
        if not _SHA256_RE.fullmatch(checksum):
            raise DocumentValidationError("Document SHA-256 checksum is invalid")
        return filename, checksum, normalized_media_type

    @staticmethod
    def _metadata_mismatch(
        version: DocumentVersion,
        stored: StoredObjectMetadata,
    ) -> str | None:
        if stored.size_bytes != version.size_bytes:
            return "Uploaded document size does not match"
        if stored.size_bytes < 1:
            return "Uploaded document is empty"
        if stored.media_type.strip().lower() != version.media_type:
            return "Uploaded document media type does not match"
        if stored.checksum_sha256 is None:
            return "Uploaded document SHA-256 checksum is unavailable"
        if stored.checksum_sha256.lower() != version.checksum_sha256:
            return "Uploaded document SHA-256 checksum does not match"
        return None

    @staticmethod
    def _required_document(
        uow: DocumentUnitOfWork,
        document_id: DocumentId,
        context: AuthorizedTenantContext,
        *,
        allow_archived: bool = False,
    ) -> Document:
        document = uow.documents.get(document_id)
        if document is None:
            raise DocumentNotFound("Document not found")
        if context.workspace_id is None or document.scope != WorkspaceScope(
            context.organization_id, context.workspace_id
        ):
            raise DocumentNotFound("Document not found")
        if document.state is DocumentState.ARCHIVED and not allow_archived:
            raise DocumentConflict("Archived document is unavailable")
        return document

    @staticmethod
    def _required_version(
        uow: DocumentUnitOfWork,
        document: Document,
        version_id: DocumentVersionId,
    ) -> DocumentVersion:
        version = uow.document_versions.get(version_id)
        if version is None or version.document != document.reference:
            raise DocumentNotFound("Document version not found")
        return version

    def _authorize_manage(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
    ) -> AuthorizedTenantContext:
        return self._authorization.authorize(
            actor,
            organization_id,
            Permission.KNOWLEDGE_MANAGE,
            workspace_id=workspace_id,
        )

    def _authorize_read(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
    ) -> AuthorizedTenantContext:
        return self._authorization.authorize(
            actor,
            organization_id,
            Permission.KNOWLEDGE_READ,
            workspace_id=workspace_id,
        )

    @staticmethod
    def _metadata(version: DocumentVersion) -> DocumentVersionMetadata:
        return DocumentVersionMetadata(
            id=version.id,
            document_id=version.document.id,
            version_number=version.version_number,
            state=version.state,
            original_filename=version.original_filename,
            checksum_sha256=version.checksum_sha256,
            size_bytes=version.size_bytes,
            media_type=version.media_type,
            content_safety_state=version.content_safety_state,
            finalized_at=version.finalized_at,
            failure_reason=version.failure_reason,
            object_deleted_at=version.object_deleted_at,
        )

    def _audit_upload_issued(
        self,
        uow: DocumentUnitOfWork,
        actor: ActorContext,
        document: Document,
        version: DocumentVersion,
        correlation: CorrelationContext | None,
    ) -> None:
        self._audit(
            uow,
            actor,
            document,
            "document.upload_issued",
            correlation,
            version=version,
            details=(("expires_in_seconds", str(self._policy.upload_ttl_seconds)),),
        )

    def _audit(
        self,
        uow: DocumentUnitOfWork,
        actor: ActorContext,
        document: Document,
        event_type: str,
        correlation: CorrelationContext | None,
        *,
        version: DocumentVersion | None = None,
        details: tuple[tuple[str, str], ...] = (),
    ) -> None:
        version_details = (
            (("document_version_id", str(version.id)),)
            if version is not None
            else ()
        )
        uow.audit_events.add(
            AuditEvent(
                id=AuditEventId.new(),
                organization_scope=OrganizationScope(document.scope.organization_id),
                workspace_scope=document.scope,
                event_type=event_type,
                target_type="document",
                target_id=str(document.id),
                actor=actor.actor,
                occurred_at=self._clock(),
                correlation=correlation
                or CorrelationContext(CorrelationId.new()),
                details=version_details + details,
            )
        )
