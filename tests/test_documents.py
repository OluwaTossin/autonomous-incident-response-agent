"""Hosted document lifecycle, authorization, and storage-boundary tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.application.documents import (
    DocumentConflict,
    DocumentFinalizationError,
    DocumentNotFound,
    DocumentUploadPolicy,
    DocumentValidationError,
    HostedDocumentService,
)
from app.auth.context import ActorContext, AuthenticationMethod
from app.authorization.permissions import Permission
from app.authorization.service import (
    AuthorizationDenied,
    AuthorizationService,
    HumanAuthorizationFacts,
    ServiceAccountAuthorizationFacts,
)
from app.documents.storage import (
    DocumentObjectNotFound,
    DocumentStorageError,
    PresignedDownload,
    PresignedUpload,
    StoredObjectMetadata,
)
from app.domain.common import ActorKind, ActorReference
from app.domain.identifiers import (
    MembershipId,
    OrganizationId,
    ServiceAccountGrantId,
    ServiceAccountId,
    UserId,
    WorkspaceId,
)
from app.domain.knowledge import (
    ContentSafetyState,
    DocumentCategory,
    DocumentState,
    DocumentVersionState,
)
from app.domain.tenancy import MembershipRole, WorkspaceAccessMode

NOW = datetime(2026, 9, 24, 18, 0, tzinfo=UTC)


def _id(identifier_type, suffix: int):
    return identifier_type(f"00000000-0000-4000-8000-{suffix:012d}")


ORG = _id(OrganizationId, 1)
OTHER_ORG = _id(OrganizationId, 2)
WORKSPACE = _id(WorkspaceId, 10)
OTHER_WORKSPACE = _id(WorkspaceId, 11)
OWNER_ID = _id(UserId, 20)
OPERATOR_ID = _id(UserId, 21)
VIEWER_ID = _id(UserId, 22)
SERVICE_ID = _id(ServiceAccountId, 23)
CHECKSUM = "a" * 64


def _human(user_id: UserId) -> ActorContext:
    return ActorContext(
        actor=ActorReference(ActorKind.HUMAN, actor_id=user_id),
        authentication_method=AuthenticationMethod.OIDC,
        issuer="https://issuer.example",
        external_subject=f"subject-{user_id}",
    )


def _service_account() -> ActorContext:
    return ActorContext(
        actor=ActorReference(ActorKind.SERVICE_ACCOUNT, actor_id=SERVICE_ID),
        authentication_method=AuthenticationMethod.SERVICE_ACCOUNT,
        credential_id="lookup-id",
    )


class Store:
    def __init__(self) -> None:
        self.documents = {}
        self.versions = {}
        self.audits = []
        self.roles = {
            OWNER_ID: MembershipRole.OWNER,
            OPERATOR_ID: MembershipRole.OPERATOR,
            VIEWER_ID: MembershipRole.VIEWER,
        }
        self.allowed_workspaces = {OPERATOR_ID: {WORKSPACE}}
        self.restricted_users: set[UserId] = set()
        self.active_workspaces = {WORKSPACE, OTHER_WORKSPACE}
        self.revoked_users: set[UserId] = set()
        self.service_permissions = frozenset({Permission.KNOWLEDGE_READ})

    def uow(self, context):
        return Uow(self)


class Facts:
    def __init__(self, store: Store) -> None:
        self.store = store

    def human_facts(self, actor, organization_id, workspace_id):
        user_id = actor.actor.actor_id
        role = self.store.roles.get(user_id)
        if (
            role is None
            or user_id in self.store.revoked_users
            or organization_id != ORG
        ):
            return None
        restricted = user_id in self.store.restricted_users
        return HumanAuthorizationFacts(
            _id(MembershipId, 100 + list(MembershipRole).index(role)),
            role,
            WorkspaceAccessMode.RESTRICTED if restricted else WorkspaceAccessMode.ALL,
            workspace_id in self.store.allowed_workspaces.get(user_id, set()),
        )

    def service_account_facts(self, actor, organization_id, workspace_id):
        if actor.actor.actor_id != SERVICE_ID or organization_id != ORG:
            return None
        return ServiceAccountAuthorizationFacts(
            _id(ServiceAccountGrantId, 200),
            self.store.service_permissions,
            WorkspaceAccessMode.ALL,
            True,
        )

    def invited_membership_id(self, actor, organization_id):
        return None

    def visible_organization_ids(self, actor):
        return (ORG,)


class Resources:
    def __init__(self, store: Store) -> None:
        self.store = store

    def is_active(self, organization_id, workspace_id):
        return organization_id == ORG and (
            workspace_id is None or workspace_id in self.store.active_workspaces
        )


class DocumentRepo:
    def __init__(self, store: Store) -> None:
        self.store = store

    def add(self, document):
        self.store.documents[document.id] = document

    def get(self, document_id):
        return self.store.documents.get(document_id)

    def list(self, *, include_archived=False):
        return [
            item
            for item in self.store.documents.values()
            if include_archived or item.state is not DocumentState.ARCHIVED
        ]

    def save(self, document, *, expected_state):
        current = self.store.documents.get(document.id)
        if current is None or current.state is not expected_state:
            raise DocumentConflict("Document state changed concurrently")
        self.store.documents[document.id] = document


class VersionRepo:
    def __init__(self, store: Store) -> None:
        self.store = store

    def add(self, version):
        if any(item.object_key == version.object_key for item in self.store.versions.values()):
            raise DocumentConflict("Document version conflicts with current state")
        self.store.versions[version.id] = version

    def get(self, version_id):
        return self.store.versions.get(version_id)

    def list_for_document(self, document_id):
        return sorted(
            (
                item
                for item in self.store.versions.values()
                if item.document.id == document_id
            ),
            key=lambda item: item.version_number,
        )

    def next_version_number(self, document_id):
        versions = self.list_for_document(document_id)
        return (versions[-1].version_number if versions else 0) + 1

    def save(self, version, *, expected_state):
        current = self.store.versions.get(version.id)
        if current is None or current.state is not expected_state:
            raise DocumentConflict("Document version state changed concurrently")
        self.store.versions[version.id] = version


class AuditRepo:
    def __init__(self, store: Store) -> None:
        self.store = store

    def add(self, event):
        self.store.audits.append(event)


class Uow:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.documents = DocumentRepo(store)
        self.document_versions = VersionRepo(store)
        self.audit_events = AuditRepo(store)
        self.snapshot = None

    def __enter__(self):
        self.snapshot = (
            dict(self.store.documents),
            dict(self.store.versions),
            list(self.store.audits),
        )
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is not None and self.snapshot is not None:
            documents, versions, audits = self.snapshot
            self.store.documents = documents
            self.store.versions = versions
            self.store.audits = audits
        return None


class FakeStorage:
    def __init__(self) -> None:
        self.uploads = {}
        self.objects = {}
        self.deleted = []
        self.fail_presign = False
        self.fail_stat = False

    def create_presigned_upload(
        self,
        object_key,
        *,
        size_bytes,
        media_type,
        checksum_sha256,
        ttl_seconds,
    ):
        if self.fail_presign:
            raise DocumentStorageError("presign failed")
        self.uploads[object_key] = StoredObjectMetadata(
            size_bytes, media_type, checksum_sha256
        )
        return PresignedUpload(
            f"https://storage.example/upload/{len(self.uploads)}",
            "PUT",
            (("if-none-match", "*"),),
            NOW + timedelta(seconds=ttl_seconds),
        )

    def create_presigned_download(
        self, object_key, *, download_filename, ttl_seconds
    ):
        return PresignedDownload(
            f"https://storage.example/download/{download_filename}",
            NOW + timedelta(seconds=ttl_seconds),
        )

    def stat(self, object_key):
        if self.fail_stat:
            raise DocumentStorageError("stat failed")
        if object_key not in self.objects:
            raise DocumentObjectNotFound("missing")
        return self.objects[object_key]

    def delete(self, object_key):
        self.deleted.append(object_key)
        self.objects.pop(object_key, None)

    def upload(self, metadata: StoredObjectMetadata | None = None):
        object_key = next(reversed(self.uploads))
        if object_key in self.objects:
            raise AssertionError("immutable object was overwritten")
        self.objects[object_key] = metadata or self.uploads[object_key]
        return object_key


def _service(store: Store, storage: FakeStorage) -> HostedDocumentService:
    return HostedDocumentService(
        AuthorizationService(Facts(store), Resources(store)),
        store.uow,
        storage,
        clock=lambda: NOW,
    )


def _initiate(service: HostedDocumentService, actor=None):
    return service.initiate_document_upload(
        actor or _human(OPERATOR_ID),
        ORG,
        WORKSPACE,
        original_filename="checkout.md",
        category=DocumentCategory.RUNBOOK,
        checksum_sha256=CHECKSUM,
        size_bytes=42,
        media_type="text/markdown",
    )


def test_document_upload_finalize_download_archive_and_audit() -> None:
    store = Store()
    storage = FakeStorage()
    service = _service(store, storage)
    intent = _initiate(service)
    object_key = storage.upload()

    finalized = service.finalize_upload(
        _human(OPERATOR_ID), ORG, WORKSPACE, intent.document.id, intent.version.id
    )
    repeated = service.finalize_upload(
        _human(OPERATOR_ID), ORG, WORKSPACE, intent.document.id, intent.version.id
    )
    download = service.issue_download(
        _human(VIEWER_ID), ORG, WORKSPACE, intent.document.id, intent.version.id
    )
    archived = service.archive_document(
        _human(OPERATOR_ID), ORG, WORKSPACE, intent.document.id
    )

    assert finalized.state is DocumentVersionState.AVAILABLE
    assert finalized.content_safety_state is ContentSafetyState.NOT_SCANNED
    assert repeated == finalized
    assert download.expires_at == NOW + timedelta(seconds=300)
    assert archived.state is DocumentState.ARCHIVED
    assert object_key in storage.objects
    with pytest.raises(DocumentConflict, match="Archived"):
        service.issue_download(
            _human(VIEWER_ID),
            ORG,
            WORKSPACE,
            intent.document.id,
            intent.version.id,
        )
    assert service.list_documents(_human(VIEWER_ID), ORG, WORKSPACE) == ()
    assert service.list_documents(
        _human(VIEWER_ID), ORG, WORKSPACE, include_archived=True
    ) == (archived,)
    assert {event.event_type for event in store.audits} == {
        "document.created",
        "document.version_created",
        "document.upload_issued",
        "document.upload_finalized",
        "document.download_issued",
        "document.archived",
    }
    audit_text = repr([event.details for event in store.audits])
    assert "https://" not in audit_text
    assert "documents/" not in audit_text


def test_new_version_has_immutable_unique_key_and_number() -> None:
    store = Store()
    storage = FakeStorage()
    service = _service(store, storage)
    first = _initiate(service)
    first_key = storage.upload()
    service.finalize_upload(
        _human(OPERATOR_ID), ORG, WORKSPACE, first.document.id, first.version.id
    )

    second = service.initiate_version_upload(
        _human(OPERATOR_ID),
        ORG,
        WORKSPACE,
        first.document.id,
        original_filename="checkout-v2.md",
        checksum_sha256="b" * 64,
        size_bytes=43,
        media_type="text/markdown",
    )
    second_key = next(reversed(storage.uploads))

    assert second.version.version_number == 2
    assert second.version.id != first.version.id
    assert second_key != first_key
    assert second_key.endswith(f"/{second.version.id}/source")
    assert "checkout-v2.md" not in second_key


@pytest.mark.parametrize(
    ("filename", "size_bytes", "media_type", "checksum"),
    [
        ("script.exe", 10, "application/octet-stream", CHECKSUM),
        ("../secret.md", 10, "text/markdown", CHECKSUM),
        ("empty.md", 0, "text/markdown", CHECKSUM),
        ("large.md", 5_242_881, "text/markdown", CHECKSUM),
        ("wrong.md", 10, "application/pdf", CHECKSUM),
        ("bad.md", 10, "text/markdown", "not-a-checksum"),
    ],
)
def test_upload_validation_fails_closed(
    filename, size_bytes, media_type, checksum
) -> None:
    service = _service(Store(), FakeStorage())
    with pytest.raises(DocumentValidationError):
        service.initiate_document_upload(
            _human(OPERATOR_ID),
            ORG,
            WORKSPACE,
            original_filename=filename,
            category=DocumentCategory.OTHER,
            checksum_sha256=checksum,
            size_bytes=size_bytes,
            media_type=media_type,
        )


@pytest.mark.parametrize(
    "metadata",
    [
        StoredObjectMetadata(41, "text/markdown", CHECKSUM),
        StoredObjectMetadata(42, "text/plain", CHECKSUM),
        StoredObjectMetadata(42, "text/markdown", "b" * 64),
        StoredObjectMetadata(42, "text/markdown", None),
    ],
)
def test_finalize_mismatch_fails_version_and_exposes_cleanup(metadata) -> None:
    store = Store()
    storage = FakeStorage()
    service = _service(store, storage)
    intent = _initiate(service)
    object_key = storage.upload(metadata)

    with pytest.raises(DocumentFinalizationError):
        service.finalize_upload(
            _human(OPERATOR_ID), ORG, WORKSPACE, intent.document.id, intent.version.id
        )

    failed = store.versions[intent.version.id]
    assert failed.state is DocumentVersionState.FAILED
    assert failed.object_deleted_at is None
    deleted = service.delete_failed_object(
        _human(OPERATOR_ID), ORG, WORKSPACE, intent.document.id, intent.version.id
    )
    assert deleted.object_deleted_at == NOW
    assert object_key in storage.deleted


def test_finalize_missing_object_remains_retryable() -> None:
    store = Store()
    storage = FakeStorage()
    service = _service(store, storage)
    intent = _initiate(service)
    with pytest.raises(DocumentFinalizationError, match="missing"):
        service.finalize_upload(
            _human(OPERATOR_ID), ORG, WORKSPACE, intent.document.id, intent.version.id
        )
    assert store.versions[intent.version.id].state is DocumentVersionState.PENDING_UPLOAD


def test_storage_errors_do_not_create_unusable_metadata() -> None:
    store = Store()
    storage = FakeStorage()
    storage.fail_presign = True
    service = _service(store, storage)
    with pytest.raises(DocumentStorageError):
        _initiate(service)
    assert store.documents == {}
    assert store.versions == {}
    assert store.audits == []


def test_authorization_workspace_and_revocation_fail_closed() -> None:
    store = Store()
    storage = FakeStorage()
    service = _service(store, storage)
    with pytest.raises(AuthorizationDenied):
        _initiate(service, _human(VIEWER_ID))
    with pytest.raises(AuthorizationDenied):
        _initiate(service, _service_account())
    with pytest.raises(AuthorizationDenied):
        service.list_documents(_human(VIEWER_ID), OTHER_ORG, WORKSPACE)

    store.restricted_users.add(OPERATOR_ID)
    with pytest.raises(AuthorizationDenied):
        service.list_documents(_human(OPERATOR_ID), ORG, OTHER_WORKSPACE)
    intent = _initiate(service)
    with pytest.raises(DocumentNotFound):
        service.get_document(
            _human(OWNER_ID), ORG, OTHER_WORKSPACE, intent.document.id
        )
    store.revoked_users.add(OPERATOR_ID)
    with pytest.raises(AuthorizationDenied):
        service.finalize_upload(
            _human(OPERATOR_ID), ORG, WORKSPACE, intent.document.id, intent.version.id
        )


def test_archived_workspace_and_document_deny_operations() -> None:
    store = Store()
    storage = FakeStorage()
    service = _service(store, storage)
    intent = _initiate(service)
    service.archive_document(
        _human(OPERATOR_ID), ORG, WORKSPACE, intent.document.id
    )
    with pytest.raises(DocumentConflict, match="Archived"):
        service.initiate_version_upload(
            _human(OPERATOR_ID),
            ORG,
            WORKSPACE,
            intent.document.id,
            original_filename="new.md",
            checksum_sha256=CHECKSUM,
            size_bytes=42,
            media_type="text/markdown",
        )

    store.active_workspaces.remove(WORKSPACE)
    with pytest.raises(AuthorizationDenied):
        service.list_documents(_human(VIEWER_ID), ORG, WORKSPACE)


def test_presign_policy_rejects_unsafe_ttl() -> None:
    with pytest.raises(ValueError, match="TTL"):
        DocumentUploadPolicy(upload_ttl_seconds=3600)
