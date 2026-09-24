"""Immutable object storage and publication for hosted knowledge bundles."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from app.knowledge.bundle import (
    CHUNKS_FILENAME,
    INDEX_FILENAME,
    MANIFEST_FILENAME,
    BuiltKnowledgeBundle,
    BundleValidationError,
    KnowledgeBundleManifest,
    artifact_prefix,
)
from app.knowledge.contracts import (
    HostedKnowledgeIndexReference,
    KnowledgeBundlePublication,
)


class ArtifactStorageError(RuntimeError):
    """Immutable artifact storage could not complete an operation."""


class ArtifactNotFound(ArtifactStorageError):
    """An expected immutable artifact object does not exist."""


class ImmutableArtifactConflict(ArtifactStorageError):
    """An immutable object key already contains different bytes."""


@dataclass(frozen=True, slots=True)
class ArtifactObjectMetadata:
    size_bytes: int
    checksum_sha256: str | None = None


class ImmutableObjectStorage(Protocol):
    def put_immutable(
        self,
        object_key: str,
        payload: bytes,
        *,
        media_type: str,
        checksum_sha256: str,
    ) -> None: ...

    def get(self, object_key: str) -> bytes: ...

    def stat(self, object_key: str) -> ArtifactObjectMetadata: ...

    def delete(self, object_key: str) -> None: ...


class KnowledgeBundlePublisher:
    """Publish files immutably, writing the completion manifest last."""

    def __init__(self, storage: ImmutableObjectStorage) -> None:
        self._storage = storage

    def publish(
        self,
        reference: HostedKnowledgeIndexReference,
        bundle: BuiltKnowledgeBundle,
    ) -> KnowledgeBundlePublication:
        bundle.manifest.require_identity(reference)
        prefix = artifact_prefix(reference)
        for name, media_type in (
            (INDEX_FILENAME, "application/octet-stream"),
            (CHUNKS_FILENAME, "application/x-ndjson"),
        ):
            payload = bundle.file_bytes(name)
            expected = bundle.manifest.file(name)
            _require_payload(payload, expected.size_bytes, expected.checksum_sha256)
            self._storage.put_immutable(
                prefix + name,
                payload,
                media_type=media_type,
                checksum_sha256=expected.checksum_sha256,
            )
        self._storage.put_immutable(
            prefix + MANIFEST_FILENAME,
            bundle.manifest_bytes,
            media_type="application/json",
            checksum_sha256=bundle.manifest_checksum_sha256,
        )
        publication = KnowledgeBundlePublication(
            artifact_prefix=prefix,
            manifest_schema_version=bundle.manifest.schema_version,
            manifest_checksum_sha256=bundle.manifest_checksum_sha256,
        )
        self.verify(reference, publication)
        return publication

    def verify(
        self,
        reference: HostedKnowledgeIndexReference,
        publication: KnowledgeBundlePublication,
    ) -> KnowledgeBundleManifest:
        expected_prefix = artifact_prefix(reference)
        if publication.artifact_prefix != expected_prefix:
            raise BundleValidationError("Artifact prefix does not match index identity")
        manifest_bytes = self._storage.get(expected_prefix + MANIFEST_FILENAME)
        if _sha256(manifest_bytes) != publication.manifest_checksum_sha256:
            raise BundleValidationError("Manifest checksum mismatch")
        manifest = KnowledgeBundleManifest.from_bytes(manifest_bytes)
        manifest.require_identity(reference)
        if manifest.schema_version != publication.manifest_schema_version:
            raise BundleValidationError("Manifest schema metadata mismatch")
        for entry in manifest.files:
            payload = self._storage.get(expected_prefix + entry.name)
            _require_payload(payload, entry.size_bytes, entry.checksum_sha256)
        return manifest

    def discover(
        self,
        reference: HostedKnowledgeIndexReference,
    ) -> KnowledgeBundlePublication | None:
        prefix = artifact_prefix(reference)
        try:
            manifest_bytes = self._storage.get(prefix + MANIFEST_FILENAME)
        except (ArtifactNotFound, KeyError):
            return None
        manifest = KnowledgeBundleManifest.from_bytes(manifest_bytes)
        manifest.require_identity(reference)
        publication = KnowledgeBundlePublication(
            artifact_prefix=prefix,
            manifest_schema_version=manifest.schema_version,
            manifest_checksum_sha256=_sha256(manifest_bytes),
        )
        self.verify(reference, publication)
        return publication


def _require_payload(payload: bytes, size_bytes: int, checksum_sha256: str) -> None:
    if len(payload) != size_bytes:
        raise BundleValidationError("Bundle file size mismatch")
    if _sha256(payload) != checksum_sha256:
        raise BundleValidationError("Bundle file checksum mismatch")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
