"""RLS-scoped PostgreSQL adapter for hosted knowledge metadata."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, sessionmaker

from app.authorization.permissions import Permission
from app.authorization.service import AuthorizedTenantContext
from app.domain.common import WorkspaceScope
from app.domain.identifiers import (
    DocumentId,
    DocumentVersionId,
    KnowledgeIndexVersionId,
)
from app.domain.knowledge import (
    ContentSafetyState,
    DocumentState,
    DocumentVersionState,
    KnowledgeIndexState,
)
from app.knowledge.contracts import (
    HostedKnowledgeIndexReference,
    INDEXABLE_DOCUMENT_CATEGORIES,
    KnowledgeSourceOrigin,
    KnowledgeSourceReference,
)
from app.persistence.postgres.models import (
    DocumentRecord,
    DocumentVersionRecord,
    KnowledgeIndexDocumentRecord,
    KnowledgeIndexVersionRecord,
)
from app.persistence.postgres.tenant import authorized_tenant_transaction


class PostgresHostedKnowledgeRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def resolve_active_index(
        self, context: AuthorizedTenantContext
    ) -> HostedKnowledgeIndexReference | None:
        scope = self._scope(context, Permission.KNOWLEDGE_READ)
        with authorized_tenant_transaction(self._session_factory, context) as session:
            record = session.scalar(
                select(KnowledgeIndexVersionRecord).where(
                    KnowledgeIndexVersionRecord.state
                    == KnowledgeIndexState.ACTIVE.value
                )
            )
            if record is None:
                return None
            source_ids = session.scalars(
                select(KnowledgeIndexDocumentRecord.document_version_id)
                .where(KnowledgeIndexDocumentRecord.index_version_id == record.id)
                .order_by(KnowledgeIndexDocumentRecord.document_version_id)
            ).all()
            return HostedKnowledgeIndexReference(
                scope=scope,
                index_version_id=KnowledgeIndexVersionId(str(record.id)),
                source_document_versions=tuple(
                    DocumentVersionId(str(value)) for value in source_ids
                ),
            )

    def select_eligible_sources(
        self, context: AuthorizedTenantContext
    ) -> tuple[KnowledgeSourceReference, ...]:
        scope = self._scope(context, Permission.KNOWLEDGE_MANAGE)
        with authorized_tenant_transaction(self._session_factory, context) as session:
            rows = session.execute(
                select(DocumentRecord, DocumentVersionRecord)
                .join(
                    DocumentVersionRecord,
                    and_(
                        DocumentVersionRecord.organization_id
                        == DocumentRecord.organization_id,
                        DocumentVersionRecord.workspace_id
                        == DocumentRecord.workspace_id,
                        DocumentVersionRecord.document_id == DocumentRecord.id,
                    ),
                )
                .where(
                    DocumentRecord.state == DocumentState.AVAILABLE.value,
                    DocumentRecord.category.in_(
                        tuple(
                            category.value for category in INDEXABLE_DOCUMENT_CATEGORIES
                        )
                    ),
                    DocumentVersionRecord.state == DocumentVersionState.AVAILABLE.value,
                    DocumentVersionRecord.content_safety_state
                    != ContentSafetyState.REJECTED.value,
                    DocumentVersionRecord.verified_checksum_sha256.is_not(None),
                    DocumentVersionRecord.verified_size_bytes.is_not(None),
                    DocumentVersionRecord.verified_media_type.is_not(None),
                    DocumentVersionRecord.object_deleted_at.is_(None),
                )
                .order_by(
                    DocumentRecord.id,
                    DocumentVersionRecord.version_number.desc(),
                )
            ).all()

        latest_by_document: dict[UUID, KnowledgeSourceReference] = {}
        for document, version in rows:
            if document.id in latest_by_document:
                continue
            if (
                version.verified_checksum_sha256 is None
                or version.verified_size_bytes is None
                or version.verified_media_type is None
            ):
                continue
            latest_by_document[document.id] = KnowledgeSourceReference(
                origin=KnowledgeSourceOrigin.TENANT,
                source=document.name,
                category=document.category,
                scope=scope,
                document_id=DocumentId(str(document.id)),
                document_version_id=DocumentVersionId(str(version.id)),
                checksum_sha256=version.verified_checksum_sha256,
                size_bytes=version.verified_size_bytes,
                media_type=version.verified_media_type,
            )
        return tuple(latest_by_document.values())

    @staticmethod
    def _scope(
        context: AuthorizedTenantContext, required: Permission
    ) -> WorkspaceScope:
        if context.permission is not required or context.workspace_id is None:
            raise PermissionError("Authorized workspace knowledge context required")
        return WorkspaceScope(context.organization_id, context.workspace_id)
