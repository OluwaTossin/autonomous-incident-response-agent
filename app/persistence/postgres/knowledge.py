"""RLS-scoped PostgreSQL adapter for hosted knowledge metadata."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.authorization.permissions import Permission
from app.authorization.service import AuthorizedTenantContext
from app.domain.common import CorrelationContext, OrganizationScope, WorkspaceScope
from app.domain.events import AuditEvent
from app.domain.identifiers import (
    AuditEventId,
    CorrelationId,
    DocumentId,
    DocumentVersionId,
    KnowledgeIndexVersionId,
)
from app.domain.knowledge import (
    ContentSafetyState,
    DocumentState,
    DocumentVersionState,
    KnowledgeIndexState,
    KnowledgeIndexVersion,
)
from app.knowledge.contracts import (
    HostedKnowledgeIndexReference,
    INDEXABLE_DOCUMENT_CATEGORIES,
    KnowledgeBundlePublication,
    KnowledgeSourceOrigin,
    KnowledgeSourceReference,
    PublishedKnowledgeIndexReference,
)
from app.persistence.postgres.mappers import (
    audit_event_to_record,
    knowledge_index_document_records,
    knowledge_index_to_record,
)
from app.persistence.postgres.models import (
    DocumentRecord,
    DocumentVersionRecord,
    KnowledgeIndexDocumentRecord,
    KnowledgeIndexVersionRecord,
)
from app.persistence.postgres.tenant import authorized_tenant_transaction
from app.persistence.postgres.usage import PostgresUsageQuotaRepository
from app.domain.usage import QuotaType, UsageType


class PostgresHostedKnowledgeRepository:
    def __init__(self, session_factory: sessionmaker[Session], quota_defaults=None, quota_observer=None) -> None:
        self._session_factory = session_factory
        self._quota_defaults = quota_defaults
        self._quota_observer = quota_observer

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

    def resolve_index_state(
        self,
        context: AuthorizedTenantContext,
        index_version_id: KnowledgeIndexVersionId,
    ) -> KnowledgeIndexState | None:
        self._scope(context, Permission.KNOWLEDGE_MANAGE)
        with authorized_tenant_transaction(self._session_factory, context) as session:
            state = session.scalar(
                select(KnowledgeIndexVersionRecord.state).where(
                    KnowledgeIndexVersionRecord.id == UUID(str(index_version_id))
                )
            )
            return KnowledgeIndexState(state) if state is not None else None

    def resolve_index_reference(
        self,
        context: AuthorizedTenantContext,
        index_version_id: KnowledgeIndexVersionId,
    ) -> HostedKnowledgeIndexReference | None:
        scope = self._scope(context, Permission.KNOWLEDGE_MANAGE)
        with authorized_tenant_transaction(self._session_factory, context) as session:
            record_id = session.scalar(
                select(KnowledgeIndexVersionRecord.id).where(
                    KnowledgeIndexVersionRecord.id == UUID(str(index_version_id))
                )
            )
            if record_id is None:
                return None
            return HostedKnowledgeIndexReference(
                scope,
                index_version_id,
                tuple(
                    DocumentVersionId(str(value))
                    for value in self._source_ids(session, record_id)
                ),
            )

    def resolve_active_publication(
        self, context: AuthorizedTenantContext
    ) -> PublishedKnowledgeIndexReference | None:
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
            if (
                record.artifact_prefix is None
                or record.manifest_schema_version is None
                or record.manifest_checksum_sha256 is None
            ):
                raise RuntimeError("Active index lacks verified publication metadata")
            source_ids = self._source_ids(session, record.id)
            return PublishedKnowledgeIndexReference(
                HostedKnowledgeIndexReference(
                    scope,
                    KnowledgeIndexVersionId(str(record.id)),
                    tuple(DocumentVersionId(str(value)) for value in source_ids),
                ),
                KnowledgeBundlePublication(
                    record.artifact_prefix,
                    record.manifest_schema_version,
                    record.manifest_checksum_sha256,
                ),
            )

    def resolve_publication(
        self,
        context: AuthorizedTenantContext,
        index_version_id: KnowledgeIndexVersionId,
    ) -> PublishedKnowledgeIndexReference | None:
        scope = self._scope(context, Permission.KNOWLEDGE_MANAGE)
        with authorized_tenant_transaction(self._session_factory, context) as session:
            record = session.get(
                KnowledgeIndexVersionRecord, UUID(str(index_version_id))
            )
            if record is None or record.state not in {
                KnowledgeIndexState.READY.value,
                KnowledgeIndexState.ACTIVE.value,
                KnowledgeIndexState.INACTIVE.value,
            }:
                return None
            if (
                record.artifact_prefix is None
                or record.manifest_schema_version is None
                or record.manifest_checksum_sha256 is None
            ):
                raise RuntimeError("Published index lacks artifact metadata")
            return PublishedKnowledgeIndexReference(
                HostedKnowledgeIndexReference(
                    scope,
                    index_version_id,
                    tuple(
                        DocumentVersionId(str(value))
                        for value in self._source_ids(session, record.id)
                    ),
                ),
                KnowledgeBundlePublication(
                    record.artifact_prefix,
                    record.manifest_schema_version,
                    record.manifest_checksum_sha256,
                ),
            )

    def create_build(
        self,
        context: AuthorizedTenantContext,
        index: KnowledgeIndexVersion,
        *,
        at: datetime,
    ) -> None:
        scope = self._scope(context, Permission.KNOWLEDGE_MANAGE)
        if index.scope != scope or index.state is not KnowledgeIndexState.BUILDING:
            raise ValueError("New knowledge index must be BUILDING in authorized scope")
        with authorized_tenant_transaction(self._session_factory, context) as session:
            usage = PostgresUsageQuotaRepository(
                session, context, self._quota_defaults, self._quota_observer
            )
            usage.lock(QuotaType.CONCURRENT_INDEX_BUILDS)
            current = int(
                session.scalar(
                    select(func.count())
                    .select_from(KnowledgeIndexVersionRecord)
                    .where(
                        KnowledgeIndexVersionRecord.state
                        == KnowledgeIndexState.BUILDING.value
                    )
                )
                or 0
            )
            usage.admit_current(
                QuotaType.CONCURRENT_INDEX_BUILDS, current, 1, at=at
            )
            session.add(knowledge_index_to_record(index))
            session.flush()
            session.add_all(knowledge_index_document_records(index))
            self._audit(session, context, index.id, "knowledge_index.build_started", at)
            usage.record(
                UsageType.KNOWLEDGE_INDEX_BUILD,
                1,
                source="knowledge_index",
                source_reference=str(index.id),
                correlation=CorrelationContext(CorrelationId.new()),
                actor=context.actor,
                at=at,
                resource_type="knowledge_index_version",
                resource_id=str(index.id),
            )

    def mark_ready(
        self,
        context: AuthorizedTenantContext,
        index_version_id: KnowledgeIndexVersionId,
        publication: KnowledgeBundlePublication,
        *,
        at: datetime,
    ) -> None:
        self._scope(context, Permission.KNOWLEDGE_MANAGE)
        with authorized_tenant_transaction(self._session_factory, context) as session:
            result = session.execute(
                update(KnowledgeIndexVersionRecord)
                .where(
                    KnowledgeIndexVersionRecord.id == UUID(str(index_version_id)),
                    KnowledgeIndexVersionRecord.state
                    == KnowledgeIndexState.BUILDING.value,
                )
                .values(
                    state=KnowledgeIndexState.READY.value,
                    published_at=at,
                    updated_at=at,
                    manifest_schema_version=publication.manifest_schema_version,
                    artifact_prefix=publication.artifact_prefix,
                    manifest_checksum_sha256=publication.manifest_checksum_sha256,
                )
            )
            if result.rowcount != 1:
                raise RuntimeError("Knowledge index is not publishable")
            self._audit(
                session,
                context,
                index_version_id,
                "knowledge_index.publication_completed",
                at,
                details=(
                    ("manifest_schema_version", str(publication.manifest_schema_version)),
                    ("manifest_checksum_sha256", publication.manifest_checksum_sha256),
                ),
            )

    def mark_failed(
        self,
        context: AuthorizedTenantContext,
        index_version_id: KnowledgeIndexVersionId,
        reason: str,
        *,
        at: datetime,
    ) -> None:
        self._scope(context, Permission.KNOWLEDGE_MANAGE)
        normalized = reason.strip() or "Bundle publication failed"
        with authorized_tenant_transaction(self._session_factory, context) as session:
            result = session.execute(
                update(KnowledgeIndexVersionRecord)
                .where(
                    KnowledgeIndexVersionRecord.id == UUID(str(index_version_id)),
                    KnowledgeIndexVersionRecord.state
                    == KnowledgeIndexState.BUILDING.value,
                )
                .values(
                    state=KnowledgeIndexState.FAILED.value,
                    failure_reason=normalized[:2000],
                    updated_at=at,
                )
            )
            if result.rowcount == 1:
                self._audit(
                    session,
                    context,
                    index_version_id,
                    "knowledge_index.publication_failed",
                    at,
                    details=(("reason", normalized[:500]),),
                )

    def record_integrity_failure(
        self,
        context: AuthorizedTenantContext,
        index_version_id: KnowledgeIndexVersionId,
        *,
        at: datetime,
    ) -> None:
        self._scope(context, Permission.KNOWLEDGE_READ)
        with authorized_tenant_transaction(self._session_factory, context) as session:
            exists = session.scalar(
                select(KnowledgeIndexVersionRecord.id).where(
                    KnowledgeIndexVersionRecord.id == UUID(str(index_version_id))
                )
            )
            if exists is None:
                return
            self._audit(
                session,
                context,
                index_version_id,
                "knowledge_index.integrity_verification_failed",
                at,
            )

    def activate(
        self,
        context: AuthorizedTenantContext,
        index_version_id: KnowledgeIndexVersionId,
        *,
        at: datetime,
        rollback: bool = False,
    ) -> PublishedKnowledgeIndexReference:
        scope = self._scope(context, Permission.KNOWLEDGE_MANAGE)
        with authorized_tenant_transaction(self._session_factory, context) as session:
            records = session.scalars(
                select(KnowledgeIndexVersionRecord)
                .order_by(KnowledgeIndexVersionRecord.id)
                .with_for_update()
            ).all()
            candidate = next(
                (record for record in records if str(record.id) == str(index_version_id)),
                None,
            )
            expected = (
                KnowledgeIndexState.INACTIVE.value
                if rollback
                else KnowledgeIndexState.READY.value
            )
            if candidate is None or candidate.state != expected:
                raise RuntimeError("Knowledge index is not eligible for activation")
            if (
                candidate.artifact_prefix is None
                or candidate.manifest_schema_version is None
                or candidate.manifest_checksum_sha256 is None
            ):
                raise RuntimeError("Knowledge index has no verified publication")
            current = next(
                (
                    record
                    for record in records
                    if record.state == KnowledgeIndexState.ACTIVE.value
                    and record.id != candidate.id
                ),
                None,
            )
            if current is not None:
                session.execute(
                    update(KnowledgeIndexVersionRecord)
                    .where(
                        KnowledgeIndexVersionRecord.id == current.id,
                        KnowledgeIndexVersionRecord.state
                        == KnowledgeIndexState.ACTIVE.value,
                    )
                    .values(
                        state=KnowledgeIndexState.INACTIVE.value,
                        superseded_at=at,
                        updated_at=at,
                    )
                )
                self._audit(
                    session,
                    context,
                    KnowledgeIndexVersionId(str(current.id)),
                    "knowledge_index.superseded",
                    at,
                    details=(("replacement_index_version_id", str(candidate.id)),),
                )
            result = session.execute(
                update(KnowledgeIndexVersionRecord)
                .where(
                    KnowledgeIndexVersionRecord.id == candidate.id,
                    KnowledgeIndexVersionRecord.state == expected,
                )
                .values(
                    state=KnowledgeIndexState.ACTIVE.value,
                    activated_at=at,
                    superseded_at=None,
                    updated_at=at,
                )
            )
            if result.rowcount != 1:
                raise RuntimeError("Concurrent knowledge index activation conflict")
            self._audit(
                session,
                context,
                index_version_id,
                (
                    "knowledge_index.rollback_activated"
                    if rollback
                    else "knowledge_index.activated"
                ),
                at,
                details=(
                    (
                        "previous_active_index_version_id",
                        str(current.id) if current else "",
                    ),
                ),
            )
            source_ids = self._source_ids(session, candidate.id)
            return PublishedKnowledgeIndexReference(
                HostedKnowledgeIndexReference(
                    scope,
                    index_version_id,
                    tuple(DocumentVersionId(str(value)) for value in source_ids),
                ),
                KnowledgeBundlePublication(
                    candidate.artifact_prefix,
                    candidate.manifest_schema_version,
                    candidate.manifest_checksum_sha256,
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

    @staticmethod
    def _source_ids(session: Session, index_id: UUID) -> list[UUID]:
        return list(
            session.scalars(
                select(KnowledgeIndexDocumentRecord.document_version_id)
                .where(KnowledgeIndexDocumentRecord.index_version_id == index_id)
                .order_by(KnowledgeIndexDocumentRecord.document_version_id)
            ).all()
        )

    @staticmethod
    def _audit(
        session: Session,
        context: AuthorizedTenantContext,
        index_version_id: KnowledgeIndexVersionId,
        event_type: str,
        at: datetime,
        *,
        details: tuple[tuple[str, str], ...] = (),
    ) -> None:
        if context.workspace_id is None:
            raise PermissionError("Authorized workspace knowledge context required")
        scope = WorkspaceScope(context.organization_id, context.workspace_id)
        session.add(
            audit_event_to_record(
                AuditEvent(
                    id=AuditEventId.new(),
                    organization_scope=OrganizationScope(context.organization_id),
                    workspace_scope=scope,
                    event_type=event_type,
                    target_type="knowledge_index_version",
                    target_id=str(index_version_id),
                    actor=context.actor,
                    occurred_at=at,
                    correlation=CorrelationContext(CorrelationId.new()),
                    details=details,
                )
            )
        )
