"""Real PostgreSQL active-index, source eligibility, and RLS tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.application.knowledge import HostedKnowledgeService
from app.authorization.permissions import Permission
from app.authorization.service import AuthorizationDenied, AuthorizationService
from app.domain.identifiers import KnowledgeIndexVersionId
from app.domain.knowledge import (
    DocumentCategory,
    KnowledgeIndexState,
    KnowledgeIndexVersion,
)
from app.persistence.postgres.authorization import (
    PostgresAuthorizationFactsRepository,
    PostgresTenantResourceValidator,
)
from app.persistence.postgres.knowledge import PostgresHostedKnowledgeRepository
from app.persistence.postgres.mappers import (
    knowledge_index_document_records,
    knowledge_index_to_record,
)
from app.persistence.postgres.models import (
    AuditEventRecord,
    DocumentVersionRecord,
    KnowledgeIndexVersionRecord,
    OrganizationMembershipRecord,
)

from .conftest import PostgresTestDatabase
from .test_document_persistence import _setup
from .test_workspace_persistence import NOW
from .test_workspace_persistence import _service as workspace_service


def _knowledge_service(runtime_session_factory) -> HostedKnowledgeService:
    authorization = AuthorizationService(
        PostgresAuthorizationFactsRepository(runtime_session_factory),
        PostgresTenantResourceValidator(runtime_session_factory),
    )
    return HostedKnowledgeService(
        authorization,
        PostgresHostedKnowledgeRepository(runtime_session_factory),
    )


def _available_document(
    document_service,
    storage,
    actor,
    organization_id,
    workspace_id,
    *,
    filename,
    category,
    checksum,
):
    intent = document_service.initiate_document_upload(
        actor,
        organization_id,
        workspace_id,
        original_filename=filename,
        category=category,
        checksum_sha256=checksum,
        size_bytes=42,
        media_type="text/markdown" if filename.endswith(".md") else "text/plain",
    )
    storage.upload_latest()
    finalized = document_service.finalize_upload(
        actor,
        organization_id,
        workspace_id,
        intent.document.id,
        intent.version.id,
    )
    return intent, finalized


def _seed_active_index(database, actor, workspace, version_ids):
    index = KnowledgeIndexVersion(
        id=KnowledgeIndexVersionId.new(),
        scope=workspace.scope,
        state=KnowledgeIndexState.ACTIVE,
        source_document_versions=tuple(version_ids),
        created_by=actor.actor,
        created_at=NOW,
        updated_at=NOW,
        activated_at=NOW,
        published_at=NOW,
        manifest_schema_version=1,
        artifact_prefix=(
            f"knowledge-indexes/{workspace.scope.organization_id}/"
            f"{workspace.id}/placeholder/"
        ),
        manifest_checksum_sha256="9" * 64,
    )
    with Session(database.migration_engine) as session, session.begin():
        session.add(knowledge_index_to_record(index))
        session.flush()
        session.add_all(knowledge_index_document_records(index))
    return index


def _seed_ready_index(database, actor, workspace, suffix):
    index_id = KnowledgeIndexVersionId(
        f"00000000-0000-4000-8000-{suffix:012d}"
    )
    index = KnowledgeIndexVersion(
        id=index_id,
        scope=workspace.scope,
        state=KnowledgeIndexState.READY,
        source_document_versions=(),
        created_by=actor.actor,
        created_at=NOW,
        updated_at=NOW,
        published_at=NOW,
        manifest_schema_version=1,
        artifact_prefix=(
            f"knowledge-indexes/{workspace.scope.organization_id}/"
            f"{workspace.id}/{index_id}/"
        ),
        manifest_checksum_sha256=f"{suffix % 10}" * 64,
    )
    with Session(database.migration_engine) as session, session.begin():
        session.add(knowledge_index_to_record(index))
    return index


def test_active_index_resolution_is_workspace_scoped_and_rls_fail_closed(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    actor, organization_id, _, workspace, storage, documents = _setup(
        postgres_database, runtime_session_factory, 70
    )
    intent, finalized = _available_document(
        documents,
        storage,
        actor,
        organization_id,
        workspace.id,
        filename="checkout.md",
        category=DocumentCategory.RUNBOOK,
        checksum="a" * 64,
    )
    index = _seed_active_index(postgres_database, actor, workspace, (finalized.id,))
    other_workspace = workspace_service(runtime_session_factory).create(
        actor,
        organization_id,
        name="Other workspace",
        slug="other-workspace",
    )
    _seed_active_index(postgres_database, actor, other_workspace, ())

    resolved = _knowledge_service(runtime_session_factory).resolve_active_index(
        actor, organization_id, workspace.id
    )

    assert resolved.scope == workspace.scope
    assert resolved.index_version_id == index.id
    assert resolved.source_document_versions == (intent.version.id,)
    with runtime_session_factory.begin() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(KnowledgeIndexVersionRecord)
            )
            == 0
        )


def test_source_selection_uses_latest_verified_available_supported_documents(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    actor, organization_id, _, workspace, storage, documents = _setup(
        postgres_database, runtime_session_factory, 80
    )
    runbook, available = _available_document(
        documents,
        storage,
        actor,
        organization_id,
        workspace.id,
        filename="checkout.md",
        category=DocumentCategory.RUNBOOK,
        checksum="b" * 64,
    )
    failed_version = documents.initiate_version_upload(
        actor,
        organization_id,
        workspace.id,
        runbook.document.id,
        original_filename="checkout-v2.md",
        checksum_sha256="c" * 64,
        size_bytes=43,
        media_type="text/markdown",
    )
    pending_version = documents.initiate_version_upload(
        actor,
        organization_id,
        workspace.id,
        runbook.document.id,
        original_filename="checkout-v3.md",
        checksum_sha256="f" * 64,
        size_bytes=44,
        media_type="text/markdown",
    )
    _available_document(
        documents,
        storage,
        actor,
        organization_id,
        workspace.id,
        filename="notes.md",
        category=DocumentCategory.OTHER,
        checksum="d" * 64,
    )
    archived, _ = _available_document(
        documents,
        storage,
        actor,
        organization_id,
        workspace.id,
        filename="retired.md",
        category=DocumentCategory.KNOWLEDGE,
        checksum="e" * 64,
    )
    documents.archive_document(
        actor, organization_id, workspace.id, archived.document.id
    )
    rejected, _ = _available_document(
        documents,
        storage,
        actor,
        organization_id,
        workspace.id,
        filename="rejected.md",
        category=DocumentCategory.KNOWLEDGE,
        checksum="1" * 64,
    )
    with Session(postgres_database.migration_engine) as session, session.begin():
        session.execute(
            update(DocumentVersionRecord)
            .where(DocumentVersionRecord.id == UUID(str(failed_version.version.id)))
            .values(state="failed", failure_reason="verification failed")
        )
        session.execute(
            update(DocumentVersionRecord)
            .where(DocumentVersionRecord.id == UUID(str(rejected.version.id)))
            .values(content_safety_state="rejected")
        )

    selection = _knowledge_service(runtime_session_factory).select_index_sources(
        actor, organization_id, workspace.id
    )

    assert len(selection.tenant_sources) == 1
    source = selection.tenant_sources[0]
    assert source.source == "checkout.md"
    assert source.document_id == runbook.document.id
    assert source.document_version_id == available.id
    assert source.checksum_sha256 == "b" * 64
    assert "documents/" not in source.source
    assert source.document_version_id not in {
        failed_version.version.id,
        pending_version.version.id,
        rejected.version.id,
    }


def test_revoked_membership_is_checked_before_knowledge_resolution(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    actor, organization_id, membership_id, workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 90
    )
    with Session(postgres_database.migration_engine) as session, session.begin():
        membership = session.get(OrganizationMembershipRecord, UUID(str(membership_id)))
        membership.state = "suspended"

    with pytest.raises(AuthorizationDenied):
        _knowledge_service(runtime_session_factory).resolve_active_index(
            actor, organization_id, workspace.id
        )


def test_activation_supersession_rollback_and_audit_are_atomic(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    actor, organization_id, _, workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 100
    )
    first = _seed_ready_index(postgres_database, actor, workspace, 501)
    second = _seed_ready_index(postgres_database, actor, workspace, 502)
    authorization = AuthorizationService(
        PostgresAuthorizationFactsRepository(runtime_session_factory),
        PostgresTenantResourceValidator(runtime_session_factory),
    )
    context = authorization.authorize(
        actor,
        organization_id,
        Permission.KNOWLEDGE_MANAGE,
        workspace_id=workspace.id,
    )
    repository = PostgresHostedKnowledgeRepository(runtime_session_factory)

    repository.activate(context, first.id, at=NOW)
    repository.activate(context, second.id, at=NOW, rollback=False)
    repository.activate(context, first.id, at=NOW, rollback=True)

    with Session(postgres_database.migration_engine) as session:
        records = {
            record.id: record
            for record in session.scalars(select(KnowledgeIndexVersionRecord)).all()
        }
        assert records[UUID(str(first.id))].state == "active"
        assert records[UUID(str(first.id))].superseded_at is None
        assert records[UUID(str(second.id))].state == "inactive"
        events = session.scalars(select(AuditEventRecord)).all()
        event_types = {event.event_type for event in events}
        assert "knowledge_index.activated" in event_types
        assert "knowledge_index.superseded" in event_types
        assert "knowledge_index.rollback_activated" in event_types
        assert all("knowledge-indexes/" not in str(event.details) for event in events)


def test_concurrent_activation_serializes_to_one_active_version(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    actor, organization_id, _, workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 110
    )
    first = _seed_ready_index(postgres_database, actor, workspace, 601)
    second = _seed_ready_index(postgres_database, actor, workspace, 602)
    authorization = AuthorizationService(
        PostgresAuthorizationFactsRepository(runtime_session_factory),
        PostgresTenantResourceValidator(runtime_session_factory),
    )
    context = authorization.authorize(
        actor,
        organization_id,
        Permission.KNOWLEDGE_MANAGE,
        workspace_id=workspace.id,
    )
    repository = PostgresHostedKnowledgeRepository(runtime_session_factory)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(repository.activate, context, index_id, at=NOW)
            for index_id in (first.id, second.id)
        ]
        for future in futures:
            future.result()

    with Session(postgres_database.migration_engine) as session:
        states = session.scalars(select(KnowledgeIndexVersionRecord.state)).all()
        assert states.count("active") == 1
        assert states.count("inactive") == 1


def test_failed_activation_leaves_previous_active_unchanged(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    actor, organization_id, _, workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 120
    )
    active = _seed_ready_index(postgres_database, actor, workspace, 701)
    invalid = _seed_ready_index(postgres_database, actor, workspace, 702)
    authorization = AuthorizationService(
        PostgresAuthorizationFactsRepository(runtime_session_factory),
        PostgresTenantResourceValidator(runtime_session_factory),
    )
    context = authorization.authorize(
        actor,
        organization_id,
        Permission.KNOWLEDGE_MANAGE,
        workspace_id=workspace.id,
    )
    repository = PostgresHostedKnowledgeRepository(runtime_session_factory)
    repository.activate(context, active.id, at=NOW)
    with Session(postgres_database.migration_engine) as session, session.begin():
        record = session.get(KnowledgeIndexVersionRecord, UUID(str(invalid.id)))
        record.state = "failed"
        record.published_at = None
        record.manifest_schema_version = None
        record.artifact_prefix = None
        record.manifest_checksum_sha256 = None
        record.failure_reason = "publication failed"

    with pytest.raises(RuntimeError, match="not eligible"):
        repository.activate(context, invalid.id, at=NOW)

    with Session(postgres_database.migration_engine) as session:
        assert session.get(
            KnowledgeIndexVersionRecord, UUID(str(active.id))
        ).state == "active"


def test_publication_and_integrity_failures_are_durably_attributed(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    actor, organization_id, _, workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 130
    )
    authorization = AuthorizationService(
        PostgresAuthorizationFactsRepository(runtime_session_factory),
        PostgresTenantResourceValidator(runtime_session_factory),
    )
    manage_context = authorization.authorize(
        actor,
        organization_id,
        Permission.KNOWLEDGE_MANAGE,
        workspace_id=workspace.id,
    )
    repository = PostgresHostedKnowledgeRepository(runtime_session_factory)
    index = KnowledgeIndexVersion(
        id=KnowledgeIndexVersionId.new(),
        scope=workspace.scope,
        state=KnowledgeIndexState.BUILDING,
        source_document_versions=(),
        created_by=actor.actor,
        created_at=NOW,
        updated_at=NOW,
    )

    repository.create_build(manage_context, index, at=NOW)
    repository.mark_failed(
        manage_context,
        index.id,
        "Bundle integrity verification failed",
        at=NOW,
    )
    read_context = authorization.authorize(
        actor,
        organization_id,
        Permission.KNOWLEDGE_READ,
        workspace_id=workspace.id,
    )
    repository.record_integrity_failure(read_context, index.id, at=NOW)

    with Session(postgres_database.migration_engine) as session:
        record = session.get(KnowledgeIndexVersionRecord, UUID(str(index.id)))
        assert record.state == "failed"
        events = session.scalars(
            select(AuditEventRecord).where(
                AuditEventRecord.target_id == str(index.id)
            )
        ).all()
        assert {event.event_type for event in events} == {
            "knowledge_index.build_started",
            "knowledge_index.publication_failed",
            "knowledge_index.integrity_verification_failed",
        }
        assert all(event.actor_id == UUID(str(actor.actor.actor_id)) for event in events)
        assert all("knowledge-indexes/" not in str(event.details) for event in events)
