"""Real PostgreSQL hosted document lifecycle and RLS tests."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.application.documents import HostedDocumentService
from app.authorization.service import AuthorizationDenied, AuthorizationService
from app.documents.storage import (
    DocumentObjectNotFound,
    PresignedDownload,
    PresignedUpload,
    StoredObjectMetadata,
)
from app.domain.identifiers import DocumentId, DocumentVersionId
from app.domain.knowledge import DocumentCategory, DocumentState, DocumentVersionState
from app.persistence.postgres.authorization import (
    PostgresAuthorizationFactsRepository,
    PostgresTenantResourceValidator,
)
from app.persistence.postgres.document_unit_of_work import PostgresDocumentUnitOfWork
from app.persistence.postgres.models import (
    AuditEventRecord,
    DocumentRecord,
    DocumentVersionRecord,
    OrganizationMembershipRecord,
)
from app.persistence.postgres.tenant import TenantContext, tenant_transaction

from .conftest import PostgresTestDatabase
from .test_workspace_persistence import (
    NOW,
    _actor,
    _seed_owner,
    _service as workspace_service,
)

CHECKSUM = "a" * 64


class DatabaseTestStorage:
    def __init__(self) -> None:
        self.expected = {}
        self.objects = {}
        self.deleted = []

    def create_presigned_upload(
        self,
        object_key,
        *,
        size_bytes,
        media_type,
        checksum_sha256,
        ttl_seconds,
    ):
        self.expected[object_key] = StoredObjectMetadata(
            size_bytes, media_type, checksum_sha256
        )
        return PresignedUpload(
            "https://storage.example/upload",
            "PUT",
            (("if-none-match", "*"),),
            NOW + timedelta(seconds=ttl_seconds),
        )

    def create_presigned_download(
        self, object_key, *, download_filename, ttl_seconds
    ):
        return PresignedDownload(
            "https://storage.example/download",
            NOW + timedelta(seconds=ttl_seconds),
        )

    def stat(self, object_key):
        try:
            return self.objects[object_key]
        except KeyError as exc:
            raise DocumentObjectNotFound("missing") from exc

    def delete(self, object_key):
        self.deleted.append(object_key)
        self.objects.pop(object_key, None)

    def upload_latest(self):
        key = next(reversed(self.expected))
        self.objects[key] = self.expected[key]


def _service(runtime_session_factory, storage) -> HostedDocumentService:
    authorization = AuthorizationService(
        PostgresAuthorizationFactsRepository(runtime_session_factory),
        PostgresTenantResourceValidator(runtime_session_factory),
    )
    return HostedDocumentService(
        authorization,
        lambda context: PostgresDocumentUnitOfWork(
            runtime_session_factory, context
        ),
        storage,
        clock=lambda: NOW,
    )


def _setup(postgres_database, runtime_session_factory, suffix=1):
    user_id, organization_id, membership_id = _seed_owner(
        postgres_database, suffix
    )
    workspace = workspace_service(runtime_session_factory).create(
        _actor(user_id),
        organization_id,
        name=f"Workspace {suffix}",
        slug=f"workspace-{suffix}",
    )
    storage = DatabaseTestStorage()
    return (
        _actor(user_id),
        organization_id,
        membership_id,
        workspace,
        storage,
        _service(runtime_session_factory, storage),
    )


def _initiate(service, actor, organization_id, workspace_id):
    return service.initiate_document_upload(
        actor,
        organization_id,
        workspace_id,
        original_filename="checkout.md",
        category=DocumentCategory.RUNBOOK,
        checksum_sha256=CHECKSUM,
        size_bytes=42,
        media_type="text/markdown",
    )


def test_document_lifecycle_versions_and_audit_are_durable(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    actor, organization_id, _, workspace, storage, service = _setup(
        postgres_database, runtime_session_factory
    )
    intent = _initiate(service, actor, organization_id, workspace.id)
    storage.upload_latest()
    finalized = service.finalize_upload(
        actor,
        organization_id,
        workspace.id,
        intent.document.id,
        intent.version.id,
    )
    second = service.initiate_version_upload(
        actor,
        organization_id,
        workspace.id,
        intent.document.id,
        original_filename="checkout-v2.md",
        checksum_sha256="b" * 64,
        size_bytes=43,
        media_type="text/markdown",
    )
    archived = service.archive_document(
        actor, organization_id, workspace.id, intent.document.id
    )

    assert finalized.state is DocumentVersionState.AVAILABLE
    assert second.version.version_number == 2
    assert archived.state is DocumentState.ARCHIVED
    with tenant_transaction(
        runtime_session_factory, TenantContext(organization_id, workspace.id)
    ) as session:
        assert session.scalar(select(func.count()).select_from(DocumentRecord)) == 1
        versions = session.scalars(
            select(DocumentVersionRecord).order_by(
                DocumentVersionRecord.version_number
            )
        ).all()
        assert [record.state for record in versions] == [
            DocumentVersionState.AVAILABLE.value,
            DocumentVersionState.PENDING_UPLOAD.value,
        ]
        events = session.scalars(select(AuditEventRecord.event_type)).all()
        assert {
            "document.created",
            "document.upload_issued",
            "document.upload_finalized",
            "document.version_created",
            "document.archived",
        } <= set(events)
        assert all("https://" not in repr(event) for event in events)


def test_document_rls_missing_and_cross_workspace_context_fail_closed(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    actor, organization_id, _, first, _, service = _setup(
        postgres_database, runtime_session_factory, 10
    )
    second = workspace_service(runtime_session_factory).create(
        actor,
        organization_id,
        name="Second",
        slug="second",
    )
    first_document = _initiate(service, actor, organization_id, first.id)
    second_document = _initiate(service, actor, organization_id, second.id)

    with runtime_session_factory.begin() as session:
        assert session.scalar(select(func.count()).select_from(DocumentRecord)) == 0
        assert (
            session.scalar(select(func.count()).select_from(DocumentVersionRecord))
            == 0
        )

    with tenant_transaction(
        runtime_session_factory, TenantContext(organization_id, first.id)
    ) as session:
        assert session.scalars(select(DocumentRecord.id)).all() == [
            UUID(str(first_document.document.id))
        ]
        assert session.scalars(select(DocumentVersionRecord.id)).all() == [
            UUID(str(first_document.version.id))
        ]
        with pytest.raises(ProgrammingError):
            session.add(
                DocumentVersionRecord(
                    id=UUID(str(DocumentVersionId.new())),
                    organization_id=UUID(str(organization_id)),
                    workspace_id=UUID(str(second.id)),
                    document_id=UUID(str(second_document.document.id)),
                    version_number=2,
                    checksum_sha256=CHECKSUM,
                    size_bytes=42,
                    media_type="text/markdown",
                    original_filename="cross.md",
                    storage_provider="s3",
                    object_key=(
                        f"documents/{organization_id}/{second.id}/"
                        f"{DocumentId.new()}/{DocumentVersionId.new()}/source"
                    ),
                    state=DocumentVersionState.PENDING_UPLOAD.value,
                    content_safety_state="not_scanned",
                    verified_checksum_sha256=None,
                    verified_size_bytes=None,
                    verified_media_type=None,
                    actor_kind=actor.actor.kind.value,
                    actor_id=UUID(str(actor.actor.actor_id)),
                    actor_system_name=None,
                    created_at=NOW,
                    updated_at=NOW,
                    finalized_at=None,
                    failure_reason=None,
                    object_deleted_at=None,
                )
            )
            session.flush()


def test_revoked_membership_is_checked_before_document_mutation(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    actor, organization_id, membership_id, workspace, _, service = _setup(
        postgres_database, runtime_session_factory, 20
    )
    intent = _initiate(service, actor, organization_id, workspace.id)
    with Session(postgres_database.migration_engine) as session, session.begin():
        membership = session.get(
            OrganizationMembershipRecord, UUID(str(membership_id))
        )
        membership.state = "suspended"

    with pytest.raises(AuthorizationDenied):
        service.archive_document(
            actor, organization_id, workspace.id, intent.document.id
        )
