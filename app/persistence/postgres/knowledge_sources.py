"""Authorized server-side reads for hosted source-document bytes."""

from __future__ import annotations

import hashlib
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, sessionmaker

from app.authorization.permissions import Permission
from app.authorization.service import AuthorizedTenantContext
from app.domain.knowledge import (
    ContentSafetyState,
    DocumentState,
    DocumentVersionState,
)
from app.knowledge.bundle import BundleValidationError
from app.knowledge.contracts import KnowledgeSourceOrigin, KnowledgeSourceReference
from app.knowledge.storage import ImmutableObjectStorage
from app.persistence.postgres.models import DocumentRecord, DocumentVersionRecord
from app.persistence.postgres.tenant import authorized_tenant_transaction


class PostgresKnowledgeSourceContentReader:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        storage: ImmutableObjectStorage,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage

    def read(
        self,
        context: AuthorizedTenantContext,
        source: KnowledgeSourceReference,
    ) -> bytes:
        if (
            context.permission is not Permission.KNOWLEDGE_MANAGE
            or context.workspace_id is None
            or source.origin is not KnowledgeSourceOrigin.TENANT
            or source.scope is None
            or source.scope.organization_id != context.organization_id
            or source.scope.workspace_id != context.workspace_id
            or source.document_id is None
            or source.document_version_id is None
        ):
            raise PermissionError("Authorized tenant source context required")
        with authorized_tenant_transaction(self._session_factory, context) as session:
            object_key = session.execute(
                select(DocumentVersionRecord.object_key)
                .join(
                    DocumentRecord,
                    and_(
                        DocumentRecord.organization_id
                        == DocumentVersionRecord.organization_id,
                        DocumentRecord.workspace_id
                        == DocumentVersionRecord.workspace_id,
                        DocumentRecord.id == DocumentVersionRecord.document_id,
                    ),
                )
                .where(
                    DocumentRecord.id == UUID(str(source.document_id)),
                    DocumentVersionRecord.id
                    == UUID(str(source.document_version_id)),
                    DocumentRecord.state == DocumentState.AVAILABLE.value,
                    DocumentVersionRecord.state
                    == DocumentVersionState.AVAILABLE.value,
                    DocumentVersionRecord.content_safety_state
                    != ContentSafetyState.REJECTED.value,
                    DocumentVersionRecord.verified_checksum_sha256
                    == source.checksum_sha256,
                    DocumentVersionRecord.verified_size_bytes == source.size_bytes,
                    DocumentVersionRecord.verified_media_type == source.media_type,
                    DocumentVersionRecord.object_deleted_at.is_(None),
                )
            ).scalar_one_or_none()
        if object_key is None:
            raise BundleValidationError("Knowledge source is no longer eligible")
        payload = self._storage.get(object_key)
        if len(payload) != source.size_bytes:
            raise BundleValidationError("Knowledge source size changed")
        if hashlib.sha256(payload).hexdigest() != source.checksum_sha256:
            raise BundleValidationError("Knowledge source checksum changed")
        return payload
