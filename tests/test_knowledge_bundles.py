"""Hosted FAISS bundle format, publication, integrity, and cache tests."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
import numpy as np
import pytest

from app.auth.context import ActorContext, AuthenticationMethod
from app.authorization.permissions import Permission
from app.authorization.service import (
    AuthorizationService,
    HumanAuthorizationFacts,
)
from app.domain.common import ActorKind, ActorReference, WorkspaceScope
from app.domain.identifiers import (
    DocumentId,
    DocumentVersionId,
    KnowledgeIndexVersionId,
    MembershipId,
    OrganizationId,
    UserId,
    WorkspaceId,
)
from app.domain.tenancy import MembershipRole, WorkspaceAccessMode
from app.knowledge.bundle import (
    BUNDLE_SCHEMA_VERSION,
    CHUNKS_FILENAME,
    INDEX_FILENAME,
    MANIFEST_FILENAME,
    BundleValidationError,
    HostedKnowledgeBundleBuilder,
    KnowledgeBundleManifest,
)
from app.knowledge.cache import VerifiedBundleCache
from app.knowledge.contracts import (
    HostedKnowledgeIndexReference,
    KnowledgeSourceOrigin,
    KnowledgeSourceReference,
    PublishedKnowledgeIndexReference,
)
from app.knowledge.storage import (
    ArtifactNotFound,
    ArtifactObjectMetadata,
    ImmutableArtifactConflict,
    KnowledgeBundlePublisher,
)

NOW = datetime(2026, 9, 24, 18, 0, tzinfo=UTC)


def _id(identifier_type, suffix: int):
    return identifier_type(f"00000000-0000-4000-8000-{suffix:012d}")


ORG = _id(OrganizationId, 1)
WORKSPACE = _id(WorkspaceId, 2)
SCOPE = WorkspaceScope(ORG, WORKSPACE)


def _actor() -> ActorContext:
    return ActorContext(
        actor=ActorReference(ActorKind.HUMAN, actor_id=_id(UserId, 3)),
        authentication_method=AuthenticationMethod.OIDC,
        issuer="https://issuer.example",
        external_subject="bundle-operator",
    )


class Facts:
    def human_facts(self, actor, organization_id, workspace_id):
        if organization_id != ORG or workspace_id != WORKSPACE:
            return None
        return HumanAuthorizationFacts(
            _id(MembershipId, 4),
            MembershipRole.OPERATOR,
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


def _context(permission=Permission.KNOWLEDGE_MANAGE):
    return AuthorizationService(Facts(), Resources()).authorize(
        _actor(), ORG, permission, workspace_id=WORKSPACE
    )


def _reference(suffix=10):
    version_id = _id(DocumentVersionId, suffix + 1)
    return HostedKnowledgeIndexReference(
        SCOPE,
        _id(KnowledgeIndexVersionId, suffix),
        (version_id,),
    )


def _source(reference, payload=b"Scale checkout workers when latency rises."):
    return KnowledgeSourceReference(
        KnowledgeSourceOrigin.TENANT,
        "checkout.md",
        "runbook",
        scope=SCOPE,
        document_id=_id(DocumentId, 20),
        document_version_id=reference.source_document_versions[0],
        checksum_sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        media_type="text/markdown",
    )


class Reader:
    def __init__(self, payload):
        self.payload = payload

    def read(self, context, source):
        assert context.workspace_id == WORKSPACE
        return self.payload


class MemoryStorage:
    def __init__(self):
        self.objects = {}
        self.get_count = 0

    def put_immutable(self, key, payload, *, media_type, checksum_sha256):
        if key in self.objects and self.objects[key] != payload:
            raise ImmutableArtifactConflict("collision")
        self.objects[key] = payload

    def get(self, key):
        self.get_count += 1
        try:
            return self.objects[key]
        except KeyError as exc:
            raise ArtifactNotFound("missing") from exc

    def stat(self, key):
        payload = self.get(key)
        return ArtifactObjectMetadata(len(payload), hashlib.sha256(payload).hexdigest())

    def delete(self, key):
        self.objects.pop(key, None)


def _embed(texts, *, batch_size, model):
    rows = [[1.0, float(index + 1)] for index, _ in enumerate(texts)]
    values = np.asarray(rows, dtype="float32")
    return values / np.linalg.norm(values, axis=1, keepdims=True)


def _builder(payload, temp_root):
    return HostedKnowledgeBundleBuilder(
        Reader(payload),
        embedding_model="fixture-embedding",
        chunk_size=24,
        chunk_overlap=4,
        embedder=_embed,
        clock=lambda: NOW,
        temp_root=temp_root,
    )


def _publish(storage, tmp_path, reference=None, payload=None):
    reference = reference or _reference()
    payload = payload or b"Scale checkout workers when latency rises."
    source = _source(reference, payload)
    publisher = KnowledgeBundlePublisher(storage)
    with _builder(payload, tmp_path).build(
        _context(), reference, (source,)
    ) as bundle:
        publication = publisher.publish(reference, bundle)
        manifest = bundle.manifest
    return PublishedKnowledgeIndexReference(reference, publication), manifest


def test_manifest_records_format_integrity_chunking_and_provenance(tmp_path) -> None:
    payload = b"Scale checkout workers when latency rises."
    reference = _reference()
    source = _source(reference, payload)
    builder = _builder(payload, tmp_path)

    with builder.build(_context(), reference, (source,)) as bundle:
        directory = bundle.directory
        assert directory.is_dir()
        manifest = KnowledgeBundleManifest.from_bytes(bundle.manifest_bytes)
        assert manifest.schema_version == BUNDLE_SCHEMA_VERSION
        assert manifest.embedding_model == "fixture-embedding"
        assert manifest.embedding_dimension == 2
        assert manifest.chunk_size == 24
        assert manifest.chunk_overlap == 4
        assert manifest.chunk_count > 1
        assert manifest.sources[0].document_version_id == str(
            reference.source_document_versions[0]
        )
        assert {entry.name for entry in manifest.files} == {
            INDEX_FILENAME,
            CHUNKS_FILENAME,
        }
        for entry in manifest.files:
            data = bundle.file_bytes(entry.name)
            assert len(data) == entry.size_bytes
            assert hashlib.sha256(data).hexdigest() == entry.checksum_sha256
        rows = [
            json.loads(line)
            for line in bundle.file_bytes(CHUNKS_FILENAME).decode().splitlines()
        ]
        assert all(row["workspace_id"] == str(WORKSPACE) for row in rows)
        assert all(
            row["knowledge_index_version_id"]
            == str(reference.index_version_id)
            for row in rows
        )
    assert not directory.exists()


def test_publication_is_manifest_last_verified_and_idempotent(tmp_path) -> None:
    storage = MemoryStorage()
    published, manifest = _publish(storage, tmp_path)
    publisher = KnowledgeBundlePublisher(storage)

    assert list(storage.objects)[-1].endswith(MANIFEST_FILENAME)
    assert publisher.verify(published.index, published.publication) == manifest
    first = dict(storage.objects)
    duplicate, _ = _publish(storage, tmp_path, published.index)
    assert duplicate == published
    assert storage.objects == first


def test_publication_and_verification_fail_closed_on_collision_or_corruption(
    tmp_path,
) -> None:
    storage = MemoryStorage()
    published, _ = _publish(storage, tmp_path)
    index_key = published.publication.artifact_prefix + INDEX_FILENAME
    storage.objects[index_key] = b"different"
    with pytest.raises(BundleValidationError, match="size mismatch|checksum mismatch"):
        KnowledgeBundlePublisher(storage).verify(
            published.index, published.publication
        )

    storage = MemoryStorage()
    storage.objects[
        "knowledge-indexes/00000000-0000-4000-8000-000000000001/"
        "00000000-0000-4000-8000-000000000002/"
        "00000000-0000-4000-8000-000000000010/index.faiss"
    ] = b"collision"
    with pytest.raises(ImmutableArtifactConflict):
        _publish(storage, tmp_path)
    assert not any(key.endswith(MANIFEST_FILENAME) for key in storage.objects)


def test_cache_downloads_once_rejects_corruption_and_redownloads(tmp_path) -> None:
    storage = MemoryStorage()
    published, _ = _publish(storage, tmp_path / "build")
    cache = VerifiedBundleCache(tmp_path / "cache", storage, max_entries=2)
    baseline_gets = storage.get_count

    with cache.acquire(published) as handle:
        assert (handle.index_dir / INDEX_FILENAME).is_file()
    first_download_gets = storage.get_count
    assert first_download_gets - baseline_gets == 3
    with cache.acquire(published):
        pass
    assert storage.get_count == first_download_gets

    cached_chunks = (
        tmp_path
        / "cache"
        / str(published.index.index_version_id)
        / CHUNKS_FILENAME
    )
    cached_chunks.write_bytes(b"corrupt")
    with cache.acquire(published):
        pass
    assert storage.get_count == first_download_gets + 3


def test_concurrent_cache_miss_has_one_download_and_eviction_is_bounded(tmp_path) -> None:
    storage = MemoryStorage()
    first, _ = _publish(storage, tmp_path / "build-1", _reference(30))
    second, _ = _publish(storage, tmp_path / "build-2", _reference(40))
    cache = VerifiedBundleCache(tmp_path / "cache", storage, max_entries=1)
    baseline = storage.get_count

    def acquire_first():
        with cache.acquire(first) as handle:
            return handle.index_dir.name

    with ThreadPoolExecutor(max_workers=4) as executor:
        assert set(executor.map(lambda _: acquire_first(), range(4))) == {
            str(first.index.index_version_id)
        }
    assert storage.get_count - baseline == 3

    with cache.acquire(second):
        pass
    visible = {
        path.name
        for path in (tmp_path / "cache").iterdir()
        if path.is_dir() and path.name != ".locks"
    }
    assert visible == {str(second.index.index_version_id)}


def test_cache_does_not_evict_in_use_bundle(tmp_path) -> None:
    storage = MemoryStorage()
    first, _ = _publish(storage, tmp_path / "build-1", _reference(50))
    second, _ = _publish(storage, tmp_path / "build-2", _reference(60))
    cache_root = tmp_path / "cache"
    cache = VerifiedBundleCache(cache_root, storage, max_entries=1)

    with cache.acquire(first) as first_handle:
        with cache.acquire(second):
            pass
        assert first_handle.index_dir.is_dir()
        assert (first_handle.index_dir / INDEX_FILENAME).is_file()

    with cache.acquire(second):
        pass
    visible = {
        path.name
        for path in cache_root.iterdir()
        if path.is_dir() and path.name != ".locks"
    }
    assert visible == {str(second.index.index_version_id)}


def test_cache_rejects_bundle_larger_than_byte_bound_and_reports_events(
    tmp_path,
) -> None:
    storage = MemoryStorage()
    published, _ = _publish(storage, tmp_path / "build")
    events = []
    cache_root = tmp_path / "cache"
    cache = VerifiedBundleCache(
        cache_root,
        storage,
        max_bytes=1,
        observe=lambda event, duration_ms, outcome: events.append(
            (event, duration_ms, outcome)
        ),
        monotonic=lambda: 1.0,
    )

    with pytest.raises(BundleValidationError, match="byte limit"):
        with cache.acquire(published):
            pass

    assert not (cache_root / str(published.index.index_version_id)).exists()
    assert [(event, outcome) for event, _, outcome in events] == [
        ("cache_miss", "succeeded"),
        ("bundle_download", "failed"),
    ]


def test_cache_rejects_integrity_valid_but_corrupt_faiss(tmp_path) -> None:
    storage = MemoryStorage()
    published, _ = _publish(storage, tmp_path / "build")
    prefix = published.publication.artifact_prefix
    index_key = prefix + INDEX_FILENAME
    manifest_key = prefix + MANIFEST_FILENAME
    storage.objects[index_key] = b"not-a-faiss-index"
    raw = json.loads(storage.objects[manifest_key])
    for entry in raw["files"]:
        if entry["name"] == INDEX_FILENAME:
            entry["size_bytes"] = len(storage.objects[index_key])
            entry["checksum_sha256"] = hashlib.sha256(
                storage.objects[index_key]
            ).hexdigest()
    manifest_bytes = (
        json.dumps(raw, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    storage.objects[manifest_key] = manifest_bytes
    changed = replace(
        published,
        publication=replace(
            published.publication,
            manifest_checksum_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        ),
    )

    with pytest.raises(BundleValidationError, match="cannot be loaded"):
        with VerifiedBundleCache(tmp_path / "cache", storage).acquire(changed):
            pass


def test_manifest_identity_and_schema_are_validated(tmp_path) -> None:
    storage = MemoryStorage()
    published, _ = _publish(storage, tmp_path)
    manifest_key = published.publication.artifact_prefix + MANIFEST_FILENAME
    raw = json.loads(storage.objects[manifest_key])
    raw["workspace_id"] = str(_id(WorkspaceId, 999))
    changed = (json.dumps(raw, sort_keys=True, separators=(",", ":")) + "\n").encode()
    storage.objects[manifest_key] = changed
    changed_publication = replace(
        published.publication,
        manifest_checksum_sha256=hashlib.sha256(changed).hexdigest(),
    )
    with pytest.raises(BundleValidationError, match="identity"):
        KnowledgeBundlePublisher(storage).verify(
            published.index, changed_publication
        )

    raw["schema_version"] = 99
    with pytest.raises(BundleValidationError, match="Unsupported"):
        KnowledgeBundleManifest.from_bytes(
            (json.dumps(raw, sort_keys=True, separators=(",", ":")) + "\n").encode()
        )
