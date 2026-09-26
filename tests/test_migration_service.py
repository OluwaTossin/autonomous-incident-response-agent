"""Migration authorization, idempotency, interruption, quota, and storage tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.application.documents import DocumentConflict
from app.auth.context import ActorContext, AuthenticationMethod
from app.authorization.permissions import Permission, role_allows
from app.authorization.service import (
    AuthorizationDenied,
    AuthorizationService,
    HumanAuthorizationFacts,
)
from app.documents.storage import (
    DocumentObjectNotFound,
    DocumentStorageError,
    StoredObjectMetadata,
)
from app.domain.common import ActorKind, ActorReference, WorkspaceScope
from app.domain.identifiers import MembershipId, OrganizationId, UserId, WorkspaceId
from app.domain.knowledge import DocumentState, DocumentVersionState
from app.domain.tenancy import MembershipRole, WorkspaceAccessMode
from app.domain.usage import QuotaExceeded, QuotaStatus, QuotaType
from app.migration.package import MigrationPackageError, export_v2_workspace
from app.migration.reporting import format_migration_report, migration_report_dict
from app.migration.service import MigrationImportError, MigrationService, _target_ids
from app.observability.metrics import InMemoryMetricSink, MigrationMetricObserver

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
ORG = OrganizationId("00000000-0000-4000-8000-000000000001")
OTHER_ORG = OrganizationId("00000000-0000-4000-8000-000000000002")
WORKSPACE = WorkspaceId("00000000-0000-4000-8000-000000000010")
OTHER_WORKSPACE = WorkspaceId("00000000-0000-4000-8000-000000000011")
OWNER = UserId("00000000-0000-4000-8000-000000000020")


def _actor() -> ActorContext:
    return ActorContext(
        ActorReference(ActorKind.HUMAN, actor_id=OWNER),
        AuthenticationMethod.OIDC,
        issuer="https://issuer.example",
        external_subject="owner",
    )


class Facts:
    def human_facts(self, actor, organization_id, workspace_id):
        if actor.actor.actor_id != OWNER or organization_id != ORG:
            return None
        return HumanAuthorizationFacts(
            MembershipId("00000000-0000-4000-8000-000000000030"),
            MembershipRole.OWNER,
            WorkspaceAccessMode.ALL,
            True,
        )

    def service_account_facts(self, actor, organization_id, workspace_id):
        return None

    def invited_membership_id(self, actor, organization_id):
        return None

    def visible_organization_ids(self, actor):
        return (ORG,)


class Resources:
    def is_active(self, organization_id, workspace_id):
        return organization_id == ORG and workspace_id == WORKSPACE


class Store:
    def __init__(self, *, max_documents=10, max_bytes=1_000_000):
        self.documents = {}
        self.versions = {}
        self.audits = []
        self.usage_events = {}
        self.max_documents = max_documents
        self.max_bytes = max_bytes

    def uow(self, context):
        return Uow(self)


class DocumentRepo:
    def __init__(self, store):
        self.store = store

    def add(self, document):
        if document.id in self.store.documents:
            raise DocumentConflict("duplicate")
        self.store.documents[document.id] = document

    def get(self, document_id):
        return self.store.documents.get(document_id)

    def list(self, *, include_archived=False):
        return list(self.store.documents.values())

    def save(self, document, *, expected_state):
        current = self.store.documents.get(document.id)
        if current is None or current.state is not expected_state:
            raise DocumentConflict("state changed")
        self.store.documents[document.id] = document

    def count_retained(self):
        return sum(
            document.state is not DocumentState.ARCHIVED
            for document in self.store.documents.values()
        )


class VersionRepo:
    def __init__(self, store):
        self.store = store

    def add(self, version):
        if version.id in self.store.versions:
            raise DocumentConflict("duplicate")
        self.store.versions[version.id] = version

    def get(self, version_id):
        return self.store.versions.get(version_id)

    def list_for_document(self, document_id):
        return [
            version
            for version in self.store.versions.values()
            if version.document.id == document_id
        ]

    def next_version_number(self, document_id):
        return 1

    def save(self, version, *, expected_state):
        current = self.store.versions.get(version.id)
        if current is None or current.state is not expected_state:
            raise DocumentConflict("state changed")
        self.store.versions[version.id] = version

    def retained_bytes(self):
        return sum(version.size_bytes for version in self.store.versions.values())


class AuditRepo:
    def __init__(self, store):
        self.store = store

    def add(self, event):
        self.store.audits.append(event)


class UsageRepo:
    def __init__(self, store):
        self.store = store

    def admit_current(self, quota_type, current, requested, *, at):
        limit = (
            self.store.max_documents
            if quota_type is QuotaType.DOCUMENT_COUNT
            else self.store.max_bytes
        )
        if current + requested > limit:
            from app.domain.usage import QuotaDecision

            raise QuotaExceeded(
                QuotaDecision(
                    QuotaStatus.REJECTED,
                    quota_type,
                    current,
                    requested,
                    limit,
                    0,
                    1,
                )
            )

    def record(
        self,
        usage_type,
        quantity,
        *,
        source,
        source_reference,
        correlation,
        actor,
        at,
        resource_type=None,
        resource_id=None,
    ):
        key = (usage_type, source, source_reference)
        value = (quantity, resource_type, resource_id)
        if key in self.store.usage_events and self.store.usage_events[key] != value:
            raise AssertionError("usage identity changed")
        inserted = key not in self.store.usage_events
        self.store.usage_events[key] = value
        return inserted


class Uow:
    def __init__(self, store):
        self.store = store

    def __enter__(self):
        self.snapshot = (
            dict(self.store.documents),
            dict(self.store.versions),
            list(self.store.audits),
            dict(self.store.usage_events),
        )
        self.documents = DocumentRepo(self.store)
        self.document_versions = VersionRepo(self.store)
        self.audit_events = AuditRepo(self.store)
        self.usage = UsageRepo(self.store)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is not None:
            (
                self.store.documents,
                self.store.versions,
                self.store.audits,
                self.store.usage_events,
            ) = self.snapshot


class Storage:
    def __init__(self):
        self.objects = {}
        self.fail_once = False

    def stat(self, object_key):
        if object_key not in self.objects:
            raise DocumentObjectNotFound("missing")
        return self.objects[object_key][0]

    def put_immutable(
        self, object_key, content, *, media_type, checksum_sha256
    ):
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
    (source / "data" / "runbooks" / "recovery.md").write_text(
        "# Recovery\nRestart safely.\n", encoding="utf-8"
    )
    return export_v2_workspace(
        source,
        tmp_path / "package",
        source_identifier="legacy/default",
        created_at=NOW,
    )


def _service(store, storage):
    return MigrationService(
        AuthorizationService(Facts(), Resources()),
        store.uow,
        storage,
        clock=lambda: NOW,
    )


def test_dry_run_has_no_durable_side_effects(tmp_path: Path) -> None:
    store = Store()
    storage = Storage()
    report = _service(store, storage).dry_run(
        _package(tmp_path), _actor(), ORG, WORKSPACE
    )
    assert report.mode == "dry-run"
    assert report.document_count_impact == 1
    assert report.document_bytes_impact > 0
    assert store.documents == {}
    assert store.versions == {}
    assert store.audits == []
    assert storage.objects == {}


def test_import_is_idempotent_and_accounts_usage_once(tmp_path: Path) -> None:
    store = Store()
    storage = Storage()
    service = _service(store, storage)
    package = _package(tmp_path)

    first = service.import_package(package, _actor(), ORG, WORKSPACE)
    second = service.import_package(package, _actor(), ORG, WORKSPACE)
    verified = service.verify(package, _actor(), ORG, WORKSPACE)
    repeated_verification = service.verify(package, _actor(), ORG, WORKSPACE)

    assert first.imported == 1
    assert second.skipped == 1
    assert verified.clean
    assert repeated_verification == verified
    assert first.migration_id == second.migration_id == verified.migration_id
    assert (
        first.records[0].target_document_id
        == second.records[0].target_document_id
        == verified.records[0].target_document_id
    )
    assert len(store.documents) == len(store.versions) == len(storage.objects) == 1
    assert len(store.usage_events) == 2
    object_key = next(iter(storage.objects))
    assert object_key.startswith(f"documents/{ORG}/{WORKSPACE}/")
    assert "recovery.md" not in object_key
    assert "data/runbooks" not in object_key
    assert {event.event_type for event in store.audits} == {
        "migration.document_prepared",
        "migration.document_imported",
    }
    details = dict(store.audits[-1].details)
    assert details["source_manifest_hash"] == package.manifest_hash
    assert "Restart safely" not in repr(store.audits)
    machine = migration_report_dict(verified)
    human = format_migration_report(verified)
    assert machine["document_count_verified"] == 1
    assert machine["document_bytes_verified"] > 0
    assert "Result: clean" in human
    assert "Restart safely" not in human


def test_target_ids_are_deterministic_within_and_distinct_across_tenants(
    tmp_path: Path,
) -> None:
    source_id = _package(tmp_path).documents[0].source_id
    scope = WorkspaceScope(ORG, WORKSPACE)

    first = _target_ids(scope, source_id)
    repeated = _target_ids(scope, source_id)
    other_workspace = _target_ids(
        WorkspaceScope(ORG, OTHER_WORKSPACE), source_id
    )
    other_organization = _target_ids(
        WorkspaceScope(OTHER_ORG, WORKSPACE), source_id
    )

    assert first == repeated
    assert first[0] != other_workspace[0]
    assert first[1] != other_workspace[1]
    assert first[0] != other_organization[0]
    assert first[1] != other_organization[1]


def test_interrupted_storage_write_resumes_without_duplicates(tmp_path: Path) -> None:
    store = Store()
    storage = Storage()
    storage.fail_once = True
    service = _service(store, storage)
    package = _package(tmp_path)

    with pytest.raises(MigrationImportError, match="storage failed"):
        service.import_package(package, _actor(), ORG, WORKSPACE)
    assert len(store.documents) == len(store.versions) == 1
    assert next(iter(store.versions.values())).state is DocumentVersionState.PENDING_UPLOAD

    report = service.import_package(package, _actor(), ORG, WORKSPACE)
    assert report.imported == 1
    assert len(store.documents) == len(store.versions) == len(storage.objects) == 1
    assert next(iter(store.versions.values())).state is DocumentVersionState.AVAILABLE


def test_quota_failure_occurs_before_partial_import(tmp_path: Path) -> None:
    store = Store(max_documents=0)
    with pytest.raises(QuotaExceeded):
        _service(store, Storage()).import_package(
            _package(tmp_path), _actor(), ORG, WORKSPACE
        )
    assert store.documents == {}


def test_package_mutation_after_preflight_is_rejected_before_writes(
    tmp_path: Path,
) -> None:
    store = Store()
    package = _package(tmp_path)
    (package.root / package.documents[0].package_path).write_text(
        "changed after validation", encoding="utf-8"
    )
    with pytest.raises(MigrationPackageError, match="changed after"):
        _service(store, Storage()).import_package(package, _actor(), ORG, WORKSPACE)
    assert store.documents == {}
    assert store.versions == {}


def test_cross_tenant_destination_is_denied(tmp_path: Path) -> None:
    with pytest.raises(AuthorizationDenied):
        _service(Store(), Storage()).preflight(
            _package(tmp_path), _actor(), OTHER_ORG, WORKSPACE
        )


def test_operator_role_does_not_gain_migration_authority() -> None:
    assert not role_allows(MembershipRole.OPERATOR, Permission.MIGRATION_IMPORT)
    assert role_allows(MembershipRole.ADMIN, Permission.MIGRATION_IMPORT)


def test_migration_metrics_have_only_bounded_non_tenant_dimensions() -> None:
    sink = InMemoryMetricSink()
    observer = MigrationMetricObserver(sink)
    observer.record_run("2", "import", "succeeded", 12)
    observer.record_record("2", "document", "imported")
    assert {record[0] for record in sink.records} == {
        "migration_runs_total",
        "migration_duration_ms",
        "migration_records_total",
    }
    for _, _, _, dimensions in sink.records:
        assert "organization_id" not in dimensions
        assert "workspace_id" not in dimensions
        assert "migration_id" not in dimensions
