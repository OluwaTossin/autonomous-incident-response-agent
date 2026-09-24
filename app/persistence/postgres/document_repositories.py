"""PostgreSQL repositories for hosted source documents."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.documents import DocumentConflict
from app.domain.identifiers import DocumentId, DocumentVersionId
from app.domain.knowledge import (
    Document,
    DocumentState,
    DocumentVersion,
    DocumentVersionState,
)
from app.persistence.postgres.mappers import (
    document_from_record,
    document_to_record,
    document_version_from_record,
    document_version_to_record,
)
from app.persistence.postgres.models import DocumentRecord, DocumentVersionRecord


class PostgresDocumentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, document: Document) -> None:
        self._session.add(document_to_record(document))
        self._session.flush()

    def get(self, document_id: DocumentId) -> Document | None:
        record = self._session.get(DocumentRecord, UUID(str(document_id)))
        return document_from_record(record) if record else None

    def list(self, *, include_archived: bool = False) -> list[Document]:
        statement = select(DocumentRecord)
        if not include_archived:
            statement = statement.where(
                DocumentRecord.state != DocumentState.ARCHIVED.value
            )
        records = self._session.scalars(
            statement.order_by(DocumentRecord.created_at, DocumentRecord.id)
        ).all()
        return [document_from_record(record) for record in records]

    def save(self, document: Document, *, expected_state: DocumentState) -> None:
        result = self._session.execute(
            update(DocumentRecord)
            .where(
                DocumentRecord.id == UUID(str(document.id)),
                DocumentRecord.organization_id
                == UUID(str(document.scope.organization_id)),
                DocumentRecord.workspace_id == UUID(str(document.scope.workspace_id)),
                DocumentRecord.state == expected_state.value,
            )
            .values(
                state=document.state.value,
                failure_reason=document.failure_reason,
                updated_at=document.updated_at,
            )
        )
        if result.rowcount != 1:
            raise DocumentConflict("Document state changed concurrently")
        self._session.flush()


class PostgresDocumentVersionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, version: DocumentVersion) -> None:
        try:
            self._session.add(document_version_to_record(version))
            self._session.flush()
        except IntegrityError as exc:
            raise DocumentConflict("Document version conflicts with current state") from exc

    def get(self, version_id: DocumentVersionId) -> DocumentVersion | None:
        record = self._session.get(DocumentVersionRecord, UUID(str(version_id)))
        return document_version_from_record(record) if record else None

    def list_for_document(self, document_id: DocumentId) -> list[DocumentVersion]:
        records = self._session.scalars(
            select(DocumentVersionRecord)
            .where(DocumentVersionRecord.document_id == UUID(str(document_id)))
            .order_by(DocumentVersionRecord.version_number)
        ).all()
        return [document_version_from_record(record) for record in records]

    def next_version_number(self, document_id: DocumentId) -> int:
        current = self._session.scalar(
            select(func.max(DocumentVersionRecord.version_number)).where(
                DocumentVersionRecord.document_id == UUID(str(document_id))
            )
        )
        return int(current or 0) + 1

    def save(
        self,
        version: DocumentVersion,
        *,
        expected_state: DocumentVersionState,
    ) -> None:
        result = self._session.execute(
            update(DocumentVersionRecord)
            .where(
                DocumentVersionRecord.id == UUID(str(version.id)),
                DocumentVersionRecord.organization_id
                == UUID(str(version.scope.organization_id)),
                DocumentVersionRecord.workspace_id
                == UUID(str(version.scope.workspace_id)),
                DocumentVersionRecord.document_id
                == UUID(str(version.document.id)),
                DocumentVersionRecord.state == expected_state.value,
            )
            .values(
                state=version.state.value,
                content_safety_state=version.content_safety_state.value,
                verified_checksum_sha256=version.verified_checksum_sha256,
                verified_size_bytes=version.verified_size_bytes,
                verified_media_type=version.verified_media_type,
                updated_at=version.updated_at,
                finalized_at=version.finalized_at,
                failure_reason=version.failure_reason,
                object_deleted_at=version.object_deleted_at,
            )
        )
        if result.rowcount != 1:
            raise DocumentConflict("Document version state changed concurrently")
        self._session.flush()

