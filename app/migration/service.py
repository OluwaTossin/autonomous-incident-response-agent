"""Authorized, quota-aware and restartable migration application service."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Protocol

from app.application.documents import DocumentUnitOfWork, DocumentUnitOfWorkFactory
from app.auth.context import ActorContext
from app.authorization.permissions import Permission
from app.authorization.service import AuthorizationService, AuthorizedTenantContext
from app.documents.storage import (
    DocumentObjectNotFound,
    DocumentStorageError,
    MigrationDocumentObjectStorage,
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
    Document,
    DocumentCategory,
    DocumentState,
    DocumentVersion,
    DocumentVersionState,
)
from app.domain.usage import QuotaType, UsageType
from app.migration.package import (
    LoadedMigrationPackage,
    MigrationRecord,
    read_package_record,
)

_MIGRATION_NAMESPACE = uuid.UUID("f4991094-9919-46e9-9b23-31fc15fbb58c")


class MigrationObserver(Protocol):
    def record_run(
        self, source_version: str, operation: str, result: str, duration_ms: int
    ) -> None: ...

    def record_record(
        self, source_version: str, record_type: str, result: str
    ) -> None: ...


class NoopMigrationObserver:
    def record_run(self, source_version, operation, result, duration_ms) -> None:
        return None

    def record_record(self, source_version, record_type, result) -> None:
        return None


class MigrationConflictMode(StrEnum):
    FAIL = "fail"
    SKIP_IDENTICAL = "skip-identical"


class MigrationImportError(RuntimeError):
    """Stable migration failure without source contents or internal stack data."""

    def __init__(self, category: str, message: str) -> None:
        self.category = category
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class MigrationRecordResult:
    source_id: str
    status: str
    target_document_id: str | None = None
    error_category: str | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class MigrationReport:
    migration_id: str
    manifest_hash: str
    organization_id: str
    workspace_id: str
    mode: str
    started_at: datetime
    completed_at: datetime
    imported: int
    skipped: int
    rejected: int
    failed: int
    document_count_impact: int
    document_bytes_impact: int
    knowledge_rebuild_required: bool
    historical_only_records: int
    unmapped_items: tuple[str, ...]
    records: tuple[MigrationRecordResult, ...]

    @property
    def clean(self) -> bool:
        return self.rejected == 0 and self.failed == 0


class MigrationService:
    def __init__(
        self,
        authorization: AuthorizationService,
        uow_factory: DocumentUnitOfWorkFactory,
        storage: MigrationDocumentObjectStorage,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        observer: MigrationObserver = NoopMigrationObserver(),
    ) -> None:
        self._authorization = authorization
        self._uow_factory = uow_factory
        self._storage = storage
        self._clock = clock
        self._observer = observer

    def preflight(
        self,
        package: LoadedMigrationPackage,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        *,
        conflict_mode: MigrationConflictMode = MigrationConflictMode.SKIP_IDENTICAL,
    ) -> MigrationReport:
        context = self._authorize(actor, organization_id, workspace_id)
        started = self._clock()
        results, count_impact, bytes_impact = self._inspect(
            package, context, conflict_mode
        )
        completed = self._clock()
        return self._report(
            package,
            context,
            "preflight",
            started,
            completed,
            results,
            count_impact,
            bytes_impact,
        )

    def dry_run(
        self,
        package: LoadedMigrationPackage,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        *,
        conflict_mode: MigrationConflictMode = MigrationConflictMode.SKIP_IDENTICAL,
    ) -> MigrationReport:
        context = self._authorize(actor, organization_id, workspace_id)
        started = self._clock()
        results, count_impact, bytes_impact = self._inspect(
            package, context, conflict_mode
        )
        return self._report(
            package,
            context,
            "dry-run",
            started,
            self._clock(),
            results,
            count_impact,
            bytes_impact,
        )

    def import_package(
        self,
        package: LoadedMigrationPackage,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        *,
        conflict_mode: MigrationConflictMode = MigrationConflictMode.SKIP_IDENTICAL,
    ) -> MigrationReport:
        context = self._authorize(actor, organization_id, workspace_id)
        started = self._clock()
        inspected, count_impact, bytes_impact = self._inspect(
            package, context, conflict_mode
        )
        rejected = tuple(result for result in inspected if result.status == "rejected")
        if rejected:
            raise MigrationImportError("conflict", "Migration preflight has conflicts")
        results: list[MigrationRecordResult] = []
        for record in package.documents:
            results.append(
                self._import_document(package, record, actor, context, conflict_mode)
            )
        return self._report(
            package,
            context,
            "import",
            started,
            self._clock(),
            tuple(results),
            count_impact,
            bytes_impact,
        )

    def verify(
        self,
        package: LoadedMigrationPackage,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
    ) -> MigrationReport:
        context = self._authorize(actor, organization_id, workspace_id)
        started = self._clock()
        results: list[MigrationRecordResult] = []
        scope = _workspace_scope(context)
        for record in package.documents:
            with self._uow_factory(context) as uow:
                document_id, version_id = _target_ids(scope, record.source_id)
                document = uow.documents.get(document_id)
                version = uow.document_versions.get(version_id)
                if not self._is_identical(document, version, record, context):
                    results.append(
                        MigrationRecordResult(
                            record.source_id,
                            "rejected",
                            str(document_id),
                            "conflict",
                            "Imported metadata does not match the migration package",
                        )
                    )
                    object_key = None
                else:
                    object_key = version.object_key
                    version_available = version.state is DocumentVersionState.AVAILABLE
            if object_key is None:
                continue
            try:
                stored = self._storage.stat(object_key)
            except (DocumentObjectNotFound, DocumentStorageError):
                stored = None
            if (
                stored is None
                or stored.size_bytes != record.size_bytes
                or stored.media_type != record.media_type
                or stored.checksum_sha256 != record.checksum_sha256
                or not version_available
            ):
                results.append(
                    MigrationRecordResult(
                        record.source_id,
                        "rejected",
                        str(document_id),
                        "checksum_mismatch",
                        "Imported object verification failed",
                    )
                )
            else:
                results.append(
                    MigrationRecordResult(record.source_id, "verified", str(document_id))
                )
        return self._report(
            package,
            context,
            "verify",
            started,
            self._clock(),
            tuple(results),
            len(package.documents),
            sum(record.size_bytes for record in package.documents),
        )

    def _inspect(
        self,
        package: LoadedMigrationPackage,
        context: AuthorizedTenantContext,
        conflict_mode: MigrationConflictMode,
    ) -> tuple[tuple[MigrationRecordResult, ...], int, int]:
        results: list[MigrationRecordResult] = []
        count_impact = 0
        bytes_impact = 0
        scope = _workspace_scope(context)
        with self._uow_factory(context) as uow:
            for record in package.documents:
                document_id, version_id = _target_ids(scope, record.source_id)
                document = uow.documents.get(document_id)
                version = uow.document_versions.get(version_id)
                if document is None and version is None:
                    results.append(
                        MigrationRecordResult(record.source_id, "accepted", str(document_id))
                    )
                    count_impact += 1
                    bytes_impact += record.size_bytes
                elif self._is_identical(document, version, record, context):
                    status = (
                        "skipped"
                        if conflict_mode is MigrationConflictMode.SKIP_IDENTICAL
                        else "rejected"
                    )
                    results.append(
                        MigrationRecordResult(
                            record.source_id,
                            status,
                            str(document_id),
                            None if status == "skipped" else "conflict",
                            "Identical record already exists",
                        )
                    )
                else:
                    results.append(
                        MigrationRecordResult(
                            record.source_id,
                            "rejected",
                            str(document_id),
                            "conflict",
                            "Source identity is bound to different destination data",
                        )
                    )
            if count_impact:
                now = self._clock()
                uow.usage.admit_current(
                    QuotaType.DOCUMENT_COUNT,
                    uow.documents.count_retained(),
                    count_impact,
                    at=now,
                )
                uow.usage.admit_current(
                    QuotaType.DOCUMENT_BYTES,
                    uow.document_versions.retained_bytes(),
                    bytes_impact,
                    at=now,
                )
        return tuple(results), count_impact, bytes_impact

    def _import_document(
        self,
        package: LoadedMigrationPackage,
        record: MigrationRecord,
        actor: ActorContext,
        context: AuthorizedTenantContext,
        conflict_mode: MigrationConflictMode,
    ) -> MigrationRecordResult:
        scope = _workspace_scope(context)
        document_id, version_id = _target_ids(scope, record.source_id)
        content = read_package_record(package, record)
        now = self._clock()
        correlation = CorrelationContext(CorrelationId.new())
        with self._uow_factory(context) as uow:
            existing_document = uow.documents.get(document_id)
            existing_version = uow.document_versions.get(version_id)
            if existing_document is not None or existing_version is not None:
                if (
                    conflict_mode is MigrationConflictMode.SKIP_IDENTICAL
                    and self._is_identical(
                        existing_document, existing_version, record, context
                    )
                    and existing_version is not None
                    and existing_version.state is DocumentVersionState.AVAILABLE
                ):
                    return MigrationRecordResult(
                        record.source_id, "skipped", str(document_id)
                    )
                if not self._is_identical(
                    existing_document, existing_version, record, context
                ):
                    raise MigrationImportError(
                        "conflict", "Migration source identity conflicts with destination"
                    )
            else:
                uow.usage.admit_current(
                    QuotaType.DOCUMENT_COUNT,
                    uow.documents.count_retained(),
                    1,
                    at=now,
                )
                uow.usage.admit_current(
                    QuotaType.DOCUMENT_BYTES,
                    uow.document_versions.retained_bytes(),
                    record.size_bytes,
                    at=now,
                )
                document = Document(
                    document_id,
                    scope,
                    PurePosixPath(record.source_path).name,
                    DocumentCategory(record.category or "other"),
                    DocumentState.PENDING_UPLOAD,
                    actor.actor,
                    now,
                    now,
                )
                version = DocumentVersion(
                    version_id,
                    scope,
                    document.reference,
                    1,
                    record.checksum_sha256,
                    record.size_bytes,
                    record.media_type,
                    document.name,
                    "s3",
                    _object_key(scope, document_id, version_id),
                    DocumentVersionState.PENDING_UPLOAD,
                    actor.actor,
                    now,
                    now,
                )
                uow.documents.add(document)
                uow.document_versions.add(version)
                self._audit(
                    uow,
                    package,
                    record,
                    actor,
                    scope,
                    document_id,
                    correlation,
                    "migration.document_prepared",
                )

        with self._uow_factory(context) as uow:
            version = uow.document_versions.get(version_id)
            if version is None:
                raise MigrationImportError("persistence_failure", "Prepared version is missing")
            object_key = version.object_key
        stored = self._store_or_verify(object_key, content, record)
        with self._uow_factory(context) as uow:
            document = uow.documents.get(document_id)
            version = uow.document_versions.get(version_id)
            if document is None or version is None:
                raise MigrationImportError("persistence_failure", "Prepared document is missing")
            if version.state is DocumentVersionState.AVAILABLE:
                return MigrationRecordResult(record.source_id, "skipped", str(document_id))
            finalized = version.finalize(
                checksum_sha256=stored.checksum_sha256 or "",
                size_bytes=stored.size_bytes,
                media_type=stored.media_type,
                at=self._clock(),
            )
            uow.document_versions.save(
                finalized, expected_state=DocumentVersionState.PENDING_UPLOAD
            )
            available = document.mark_available(at=self._clock())
            uow.documents.save(available, expected_state=DocumentState.PENDING_UPLOAD)
            source_reference = f"migration:{record.source_id}"
            uow.usage.record(
                UsageType.DOCUMENT_VERSION_CREATED,
                1,
                source="v2_migration",
                source_reference=source_reference,
                correlation=correlation,
                actor=actor.actor,
                at=self._clock(),
                resource_type="document_version",
                resource_id=str(version_id),
            )
            uow.usage.record(
                UsageType.DOCUMENT_BYTES_STORED,
                record.size_bytes,
                source="v2_migration",
                source_reference=source_reference,
                correlation=correlation,
                actor=actor.actor,
                at=self._clock(),
                resource_type="document_version",
                resource_id=str(version_id),
            )
            self._audit(
                uow,
                package,
                record,
                actor,
                scope,
                document_id,
                correlation,
                "migration.document_imported",
            )
        return MigrationRecordResult(record.source_id, "imported", str(document_id))

    def _store_or_verify(
        self, object_key: str, content: bytes, record: MigrationRecord
    ) -> StoredObjectMetadata:
        try:
            stored = self._storage.stat(object_key)
        except DocumentObjectNotFound:
            try:
                stored = self._storage.put_immutable(
                    object_key,
                    content,
                    media_type=record.media_type,
                    checksum_sha256=record.checksum_sha256,
                )
            except DocumentStorageError as exc:
                try:
                    stored = self._storage.stat(object_key)
                except (DocumentObjectNotFound, DocumentStorageError):
                    raise MigrationImportError(
                        "storage_failure", "Migration document storage failed"
                    ) from exc
        except DocumentStorageError as exc:
            raise MigrationImportError(
                "storage_failure", "Migration document storage inspection failed"
            ) from exc
        if (
            stored.size_bytes != record.size_bytes
            or stored.media_type != record.media_type
            or stored.checksum_sha256 != record.checksum_sha256
        ):
            raise MigrationImportError(
                "conflict", "Immutable destination object does not match source"
            )
        return stored

    @staticmethod
    def _is_identical(document, version, record, context) -> bool:
        if document is None or version is None or context.workspace_id is None:
            return False
        scope = WorkspaceScope(context.organization_id, context.workspace_id)
        return (
            document.scope == scope
            and version.scope == scope
            and version.document == document.reference
            and document.name == PurePosixPath(record.source_path).name
            and document.category.value == record.category
            and version.checksum_sha256 == record.checksum_sha256
            and version.size_bytes == record.size_bytes
            and version.media_type == record.media_type
        )

    def _authorize(self, actor, organization_id, workspace_id):
        return self._authorization.authorize(
            actor,
            organization_id,
            Permission.MIGRATION_IMPORT,
            workspace_id=workspace_id,
        )

    def _audit(
        self,
        uow: DocumentUnitOfWork,
        package: LoadedMigrationPackage,
        record: MigrationRecord,
        actor: ActorContext,
        scope: WorkspaceScope,
        document_id: DocumentId,
        correlation: CorrelationContext,
        event_type: str,
    ) -> None:
        uow.audit_events.add(
            AuditEvent(
                AuditEventId.new(),
                OrganizationScope(scope.organization_id),
                event_type,
                "document",
                str(document_id),
                actor.actor,
                self._clock(),
                correlation,
                workspace_scope=scope,
                details=(
                    ("migration_id", _migration_id(package.manifest_hash, scope)),
                    ("source_manifest_hash", package.manifest_hash),
                    ("source_record_id", record.source_id),
                    ("source_version", package.manifest.source_version),
                ),
            )
        )

    def _report(
        self,
        package,
        context,
        mode,
        started,
        completed,
        records,
        count_impact,
        bytes_impact,
    ):
        scope = WorkspaceScope(context.organization_id, context.workspace_id)
        report = MigrationReport(
            migration_id=_migration_id(package.manifest_hash, scope),
            manifest_hash=package.manifest_hash,
            organization_id=str(context.organization_id),
            workspace_id=str(context.workspace_id),
            mode=mode,
            started_at=started,
            completed_at=completed,
            imported=sum(item.status == "imported" for item in records),
            skipped=sum(item.status == "skipped" for item in records),
            rejected=sum(item.status == "rejected" for item in records),
            failed=sum(item.status == "failed" for item in records),
            document_count_impact=count_impact,
            document_bytes_impact=bytes_impact,
            knowledge_rebuild_required=bool(package.documents),
            historical_only_records=dict(package.manifest.counts).get(
                "historical_only", 0
            ),
            unmapped_items=package.manifest.omitted,
            records=tuple(sorted(records, key=lambda item: item.source_id)),
        )
        for item in report.records:
            self._observer.record_record(
                package.manifest.source_version, "document", item.status
            )
        duration_ms = max(
            0, int((report.completed_at - report.started_at).total_seconds() * 1000)
        )
        self._observer.record_run(
            package.manifest.source_version,
            mode,
            "succeeded" if report.clean else "failed",
            duration_ms,
        )
        return report


def _target_ids(
    scope: WorkspaceScope, source_id: str
) -> tuple[DocumentId, DocumentVersionId]:
    tenant_identity = f"{scope.organization_id}:{scope.workspace_id}:{source_id}"
    document_uuid = uuid.uuid5(
        _MIGRATION_NAMESPACE, f"document:{tenant_identity}"
    )
    version_uuid = uuid.uuid5(
        _MIGRATION_NAMESPACE, f"document-version:{tenant_identity}"
    )
    return DocumentId(str(document_uuid)), DocumentVersionId(str(version_uuid))


def _workspace_scope(context: AuthorizedTenantContext) -> WorkspaceScope:
    if context.workspace_id is None:  # Defensive: migration permission is workspace-scoped.
        raise MigrationImportError(
            "authorization_failed", "Migration requires an authorized workspace"
        )
    return WorkspaceScope(context.organization_id, context.workspace_id)


def _object_key(scope, document_id, version_id) -> str:
    return (
        f"documents/{scope.organization_id}/{scope.workspace_id}/"
        f"{document_id}/{version_id}/source"
    )


def _migration_id(manifest_hash: str, scope: WorkspaceScope) -> str:
    return str(
        uuid.uuid5(
            _MIGRATION_NAMESPACE,
            f"migration:{scope.organization_id}:{scope.workspace_id}:{manifest_hash}",
        )
    )
