"""Real PostgreSQL migration idempotency, RLS, provenance, and resume tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.authorization.service import AuthorizationDenied, AuthorizationService
from app.documents.storage import (
    DocumentObjectNotFound,
    DocumentStorageError,
    StoredObjectMetadata,
)
from app.domain.knowledge import DocumentVersionState
from app.migration.package import export_v2_workspace
from app.migration.service import MigrationImportError, MigrationService
from app.persistence.postgres.authorization import (
    PostgresAuthorizationFactsRepository,
    PostgresTenantResourceValidator,
)
from app.persistence.postgres.document_unit_of_work import PostgresDocumentUnitOfWork
from app.persistence.postgres.models import (
    AuditEventRecord,
    DocumentRecord,
    DocumentVersionRecord,
    UsageEventRecord,
)
from app.persistence.postgres.tenant import TenantContext, tenant_transaction

from .conftest import PostgresTestDatabase
from .test_workspace_persistence import NOW, _actor, _seed_owner, _service as workspace_service


class MigrationStorage:
    def __init__(self) -> None:
        self.objects = {}
        self.fail_once = False

    def stat(self, object_key):
        try:
            return self.objects[object_key][0]
        except KeyError as exc:
            raise DocumentObjectNotFound("missing") from exc

    def put_immutable(self, object_key, content, *, media_type, checksum_sha256):
        if self.fail_once:
            self.fail_once = False
            raise DocumentStorageError("interrupted")
        if object_key in self.objects:
            raise AssertionError("immutable object overwritten")
        metadata = StoredObjectMetadata(len(content), media_type, checksum_sha256)
        self.objects[object_key] = (metadata, content)
        return metadata


def _package(tmp_path: Path):
    source = tmp_path / "v2"
    (source / "data" / "runbooks").mkdir(parents=True)
    (source / "data" / "runbooks" / "database.md").write_text(
        "# Database recovery\nUse the approved runbook.\n", encoding="utf-8"
    )
    return export_v2_workspace(
        source,
        tmp_path / "package",
        source_identifier="postgres-fixture/default",
        created_at=NOW,
    )


def _setup(postgres_database, runtime_session_factory, storage):
    user_id, organization_id, _ = _seed_owner(postgres_database, 71)
    workspace = workspace_service(runtime_session_factory).create(
        _actor(user_id),
        organization_id,
        name="Migration workspace",
        slug="migration-workspace",
    )
    authorization = AuthorizationService(
        PostgresAuthorizationFactsRepository(runtime_session_factory),
        PostgresTenantResourceValidator(runtime_session_factory),
    )
    service = MigrationService(
        authorization,
        lambda context: PostgresDocumentUnitOfWork(runtime_session_factory, context),
        storage,
        clock=lambda: NOW,
    )
    return _actor(user_id), organization_id, workspace, service


def test_postgres_import_is_idempotent_rls_scoped_and_audited(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
    tmp_path: Path,
) -> None:
    storage = MigrationStorage()
    actor, organization_id, workspace, service = _setup(
        postgres_database, runtime_session_factory, storage
    )
    package = _package(tmp_path)

    first = service.import_package(package, actor, organization_id, workspace.id)
    second = service.import_package(package, actor, organization_id, workspace.id)
    verification = service.verify(package, actor, organization_id, workspace.id)

    assert first.imported == 1
    assert second.skipped == 1
    assert verification.clean
    with tenant_transaction(
        runtime_session_factory, TenantContext(organization_id, workspace.id)
    ) as session:
        assert session.scalar(select(func.count()).select_from(DocumentRecord)) == 1
        assert session.scalar(select(func.count()).select_from(DocumentVersionRecord)) == 1
        assert session.scalar(select(func.count()).select_from(UsageEventRecord)) == 2
        events = session.scalars(select(AuditEventRecord)).all()
        assert {event.event_type for event in events} == {
            "migration.document_prepared",
            "migration.document_imported",
            "workspace.created",
        }
        imported = next(
            event for event in events if event.event_type == "migration.document_imported"
        )
        assert imported.details["source_manifest_hash"] == package.manifest_hash

    other_user, other_org, _ = _seed_owner(postgres_database, 72)
    with pytest.raises(AuthorizationDenied):
        service.preflight(package, _actor(other_user), other_org, workspace.id)


def test_postgres_import_resumes_pending_document_after_storage_failure(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
    tmp_path: Path,
) -> None:
    storage = MigrationStorage()
    storage.fail_once = True
    actor, organization_id, workspace, service = _setup(
        postgres_database, runtime_session_factory, storage
    )
    package = _package(tmp_path)

    with pytest.raises(MigrationImportError, match="storage failed"):
        service.import_package(package, actor, organization_id, workspace.id)
    with tenant_transaction(
        runtime_session_factory, TenantContext(organization_id, workspace.id)
    ) as session:
        state = session.scalar(select(DocumentVersionRecord.state))
        assert state == DocumentVersionState.PENDING_UPLOAD.value

    resumed = service.import_package(package, actor, organization_id, workspace.id)
    assert resumed.imported == 1
    with tenant_transaction(
        runtime_session_factory, TenantContext(organization_id, workspace.id)
    ) as session:
        assert session.scalar(select(DocumentVersionRecord.state)) == (
            DocumentVersionState.AVAILABLE.value
        )


def test_same_package_imports_with_distinct_ids_in_two_organizations(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
    tmp_path: Path,
) -> None:
    first_user, first_org, _ = _seed_owner(postgres_database, 81)
    second_user, second_org, _ = _seed_owner(postgres_database, 82)
    workspace_service_instance = workspace_service(runtime_session_factory)
    first_workspace = workspace_service_instance.create(
        _actor(first_user),
        first_org,
        name="First migration workspace",
        slug="first-migration-workspace",
    )
    second_workspace = workspace_service_instance.create(
        _actor(second_user),
        second_org,
        name="Second migration workspace",
        slug="second-migration-workspace",
    )
    storage = MigrationStorage()
    authorization = AuthorizationService(
        PostgresAuthorizationFactsRepository(runtime_session_factory),
        PostgresTenantResourceValidator(runtime_session_factory),
    )
    service = MigrationService(
        authorization,
        lambda context: PostgresDocumentUnitOfWork(runtime_session_factory, context),
        storage,
        clock=lambda: NOW,
    )
    package = _package(tmp_path)

    first = service.import_package(
        package, _actor(first_user), first_org, first_workspace.id
    )
    second = service.import_package(
        package, _actor(second_user), second_org, second_workspace.id
    )
    first_document_id = first.records[0].target_document_id
    second_document_id = second.records[0].target_document_id

    assert first.imported == second.imported == 1
    assert first_document_id != second_document_id
    assert first.migration_id != second.migration_id
    assert len(storage.objects) == 2

    target_version_ids = []
    for organization_id, workspace_id, document_id in (
        (first_org, first_workspace.id, first_document_id),
        (second_org, second_workspace.id, second_document_id),
    ):
        with tenant_transaction(
            runtime_session_factory, TenantContext(organization_id, workspace_id)
        ) as session:
            assert session.scalar(select(func.count()).select_from(DocumentRecord)) == 1
            assert str(session.scalar(select(DocumentRecord.id))) == document_id
            target_version_ids.append(
                str(session.scalar(select(DocumentVersionRecord.id)))
            )
            assert session.scalar(select(func.count()).select_from(UsageEventRecord)) == 2
    assert target_version_ids[0] != target_version_ids[1]

    with tenant_transaction(
        runtime_session_factory,
        TenantContext(first_org, second_workspace.id),
    ) as session:
        assert session.scalar(select(func.count()).select_from(DocumentRecord)) == 0

    first_verification = service.verify(
        package, _actor(first_user), first_org, first_workspace.id
    )
    assert first_verification == service.verify(
        package, _actor(first_user), first_org, first_workspace.id
    )
