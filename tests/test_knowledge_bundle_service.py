"""Application orchestration tests for hosted bundle publication and rollback."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import numpy as np
import pytest

from app.application.knowledge_bundles import HostedKnowledgeBundleService
from app.auth.context import ActorContext, AuthenticationMethod
from app.authorization.service import (
    AuthorizationService,
    HumanAuthorizationFacts,
)
from app.domain.common import ActorKind, ActorReference, WorkspaceScope
from app.domain.identifiers import (
    DocumentId,
    DocumentVersionId,
    MembershipId,
    OrganizationId,
    UserId,
    WorkspaceId,
)
from app.domain.tenancy import MembershipRole, WorkspaceAccessMode
from app.knowledge.bundle import HostedKnowledgeBundleBuilder
from app.knowledge.contracts import (
    HostedKnowledgeIndexReference,
    KnowledgeSourceOrigin,
    KnowledgeSourceReference,
    PublishedKnowledgeIndexReference,
)
from app.knowledge.storage import (
    ArtifactObjectMetadata,
    ArtifactStorageError,
    KnowledgeBundlePublisher,
)

NOW = datetime(2026, 9, 24, 19, 0, tzinfo=UTC)


def _id(identifier_type, suffix):
    return identifier_type(f"00000000-0000-4000-8000-{suffix:012d}")


ORG = _id(OrganizationId, 1)
WORKSPACE = _id(WorkspaceId, 2)
PAYLOAD = b"Restart checkout workers after draining traffic."


def _actor():
    return ActorContext(
        actor=ActorReference(ActorKind.HUMAN, actor_id=_id(UserId, 3)),
        authentication_method=AuthenticationMethod.OIDC,
        issuer="https://issuer.example",
        external_subject="operator",
    )


class Facts:
    def human_facts(self, actor, organization_id, workspace_id):
        return HumanAuthorizationFacts(
            _id(MembershipId, 4),
            MembershipRole.OPERATOR,
            WorkspaceAccessMode.ALL,
            organization_id == ORG and workspace_id == WORKSPACE,
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


class Reader:
    def read(self, context, source):
        return PAYLOAD


class Storage:
    def __init__(self, fail_after=None):
        self.objects = {}
        self.puts = 0
        self.fail_after = fail_after

    def put_immutable(self, key, payload, *, media_type, checksum_sha256):
        self.puts += 1
        if self.fail_after is not None and self.puts > self.fail_after:
            raise ArtifactStorageError("partial upload")
        if key in self.objects and self.objects[key] != payload:
            raise ArtifactStorageError("collision")
        self.objects[key] = payload

    def get(self, key):
        return self.objects[key]

    def stat(self, key):
        payload = self.objects[key]
        return ArtifactObjectMetadata(len(payload), hashlib.sha256(payload).hexdigest())

    def delete(self, key):
        self.objects.pop(key, None)


class Repository:
    def __init__(self, source):
        self.source = source
        self.created = None
        self.ready = None
        self.failed = None
        self.activations = []
        self.publications = {}
        self.active = None
        self.integrity_failures = []

    def select_eligible_sources(self, context):
        return (self.source,)

    def create_build(self, context, index, *, at):
        self.created = index

    def mark_ready(self, context, index_version_id, publication, *, at):
        self.ready = index_version_id
        self.publications[index_version_id] = PublishedKnowledgeIndexReference(
            HostedKnowledgeIndexReference(
                self.created.scope,
                index_version_id,
                self.created.source_document_versions,
            ),
            publication,
        )

    def mark_failed(self, context, index_version_id, reason, *, at):
        self.failed = (index_version_id, reason)

    def activate(self, context, index_version_id, *, at, rollback=False):
        assert index_version_id in self.publications
        self.activations.append((index_version_id, rollback))
        self.active = self.publications[index_version_id]
        return self.active

    def resolve_publication(self, context, index_version_id):
        return self.publications.get(index_version_id)

    def resolve_active_publication(self, context):
        return self.active

    def record_integrity_failure(self, context, index_version_id, *, at):
        self.integrity_failures.append(index_version_id)


class Observer:
    def __init__(self):
        self.events = []

    def record(self, event, duration_ms, outcome):
        self.events.append((event, outcome))


def _source():
    return KnowledgeSourceReference(
        KnowledgeSourceOrigin.TENANT,
        "checkout.md",
        "runbook",
        scope=WorkspaceScope(ORG, WORKSPACE),
        document_id=_id(DocumentId, 5),
        document_version_id=_id(DocumentVersionId, 6),
        checksum_sha256=hashlib.sha256(PAYLOAD).hexdigest(),
        size_bytes=len(PAYLOAD),
        media_type="text/markdown",
    )


def _embed(texts, *, batch_size, model):
    return np.asarray([[1.0, 0.0] for _ in texts], dtype="float32")


def _service(tmp_path, repository, storage, observer=None):
    return HostedKnowledgeBundleService(
        AuthorizationService(Facts(), Resources()),
        repository,
        HostedKnowledgeBundleBuilder(
            Reader(),
            embedding_model="fixture",
            embedder=_embed,
            clock=lambda: NOW,
            temp_root=tmp_path,
        ),
        KnowledgeBundlePublisher(storage),
        observer=observer or Observer(),
        clock=lambda: NOW,
        monotonic=lambda: 1.0,
    )


def test_verified_publication_becomes_ready_before_activation(tmp_path) -> None:
    repository = Repository(_source())
    storage = Storage()
    observer = Observer()
    service = _service(tmp_path, repository, storage, observer)

    result = service.build_publish_activate(_actor(), ORG, WORKSPACE)

    assert repository.ready == result.index.index_version_id
    assert repository.failed is None
    assert repository.activations == [(result.index.index_version_id, False)]
    assert observer.events == [
        ("bundle_build", "succeeded"),
        ("bundle_publish", "succeeded"),
        ("bundle_activation", "succeeded"),
    ]


def test_partial_publication_fails_without_activation(tmp_path) -> None:
    repository = Repository(_source())
    service = _service(tmp_path, repository, Storage(fail_after=1))

    with pytest.raises(ArtifactStorageError):
        service.build_publish_activate(_actor(), ORG, WORKSPACE)

    assert repository.ready is None
    assert repository.failed[0] == repository.created.id
    assert repository.activations == []


def test_rollback_verifies_existing_artifact_before_activation(tmp_path) -> None:
    repository = Repository(_source())
    storage = Storage()
    service = _service(tmp_path, repository, storage)
    published = service.build_publish_activate(_actor(), ORG, WORKSPACE)
    repository.activations.clear()

    rolled_back = service.rollback(
        _actor(), ORG, WORKSPACE, published.index.index_version_id
    )

    assert rolled_back == published
    assert repository.activations == [(published.index.index_version_id, True)]

    storage.objects[
        published.publication.artifact_prefix + "manifest.json"
    ] = b"corrupt"
    repository.activations.clear()
    with pytest.raises(Exception):
        service.rollback(_actor(), ORG, WORKSPACE, published.index.index_version_id)
    assert repository.activations == []


def test_active_resolution_records_integrity_failure(tmp_path) -> None:
    repository = Repository(_source())
    storage = Storage()
    observer = Observer()
    service = _service(tmp_path, repository, storage, observer)
    published = service.build_publish_activate(_actor(), ORG, WORKSPACE)
    storage.objects[
        published.publication.artifact_prefix + "manifest.json"
    ] = b"corrupt"

    with pytest.raises(Exception):
        service.resolve_active(_actor(), ORG, WORKSPACE)

    assert repository.integrity_failures == [published.index.index_version_id]
    assert observer.events[-1] == ("bundle_verify", "failed")
