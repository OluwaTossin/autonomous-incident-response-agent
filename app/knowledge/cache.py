"""Checksum-verified bounded local cache for immutable hosted FAISS bundles."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from app.knowledge.bundle import (
    MANIFEST_FILENAME,
    BundleValidationError,
    KnowledgeBundleManifest,
)
from app.knowledge.contracts import (
    LocalFaissIndexHandle,
    PublishedKnowledgeIndexReference,
)
from app.knowledge.storage import ImmutableObjectStorage
from app.rag.index_store import load_index_bundle
from app.rag.retrieve import LocalFaissRetriever, RetrievalHit


class VerifiedBundleCache:
    def __init__(
        self,
        root: Path,
        storage: ImmutableObjectStorage,
        *,
        max_entries: int = 8,
        max_bytes: int = 2 * 1024 * 1024 * 1024,
        observe: Callable[[str, int, str], None] = lambda event, duration, outcome: None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_entries < 1 or max_bytes < 1:
            raise ValueError("Cache bounds must be positive")
        self._root = root
        self._storage = storage
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._observe = observe
        self._monotonic = monotonic
        self._locks = root / ".locks"
        self._root.mkdir(parents=True, exist_ok=True)
        self._locks.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def acquire(
        self, reference: PublishedKnowledgeIndexReference
    ) -> Iterator[LocalFaissIndexHandle]:
        key = str(reference.index.index_version_id)
        lock_path = self._locks / f"{key}.lock"
        with _file_lock(lock_path, exclusive=True) as lock_stream:
            directory, manifest = self._ensure(reference)
            self._evict(exclude={key})
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_SH)
            manifest = self._verify_directory(directory, reference)
            os.utime(directory, None)
            yield LocalFaissIndexHandle(
                directory,
                format_version=manifest.format_version,
                embedding_model=manifest.embedding_model,
            )

    def _ensure(
        self, reference: PublishedKnowledgeIndexReference
    ) -> tuple[Path, KnowledgeBundleManifest]:
        key = str(reference.index.index_version_id)
        final = self._root / key
        if final.is_dir():
            verify_started = self._monotonic()
            try:
                manifest = self._verify_directory(final, reference)
                self._record("cache_hit", verify_started, "succeeded")
                return final, manifest
            except (BundleValidationError, OSError, ValueError):
                self._record("bundle_verify", verify_started, "failed")
                shutil.rmtree(final, ignore_errors=True)

        self._record("cache_miss", self._monotonic(), "succeeded")
        download_started = self._monotonic()
        temporary = Path(tempfile.mkdtemp(prefix=f".{key}.", dir=self._root))
        try:
            prefix = reference.publication.artifact_prefix
            manifest_bytes = self._storage.get(prefix + MANIFEST_FILENAME)
            if _sha256(manifest_bytes) != reference.publication.manifest_checksum_sha256:
                raise BundleValidationError("Manifest checksum mismatch")
            manifest = KnowledgeBundleManifest.from_bytes(manifest_bytes)
            manifest.require_identity(reference.index)
            if manifest.schema_version != reference.publication.manifest_schema_version:
                raise BundleValidationError("Manifest schema metadata mismatch")
            (temporary / MANIFEST_FILENAME).write_bytes(manifest_bytes)
            for entry in manifest.files:
                payload = self._storage.get(prefix + entry.name)
                if len(payload) != entry.size_bytes or _sha256(payload) != entry.checksum_sha256:
                    raise BundleValidationError("Downloaded bundle file failed integrity check")
                (temporary / entry.name).write_bytes(payload)
            (temporary / "meta.json").write_text(
                json.dumps(
                    {
                        "embedding_model": manifest.embedding_model,
                        "dim": manifest.embedding_dimension,
                        "num_chunks": manifest.chunk_count,
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            self._validate_faiss(temporary, manifest)
            if _directory_size(temporary) > self._max_bytes:
                raise BundleValidationError("Bundle exceeds local cache byte limit")
            os.replace(temporary, final)
            self._record("bundle_download", download_started, "succeeded")
            return final, manifest
        except Exception:
            self._record("bundle_download", download_started, "failed")
            raise
        finally:
            if temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)

    def _verify_directory(
        self,
        directory: Path,
        reference: PublishedKnowledgeIndexReference,
    ) -> KnowledgeBundleManifest:
        manifest_bytes = (directory / MANIFEST_FILENAME).read_bytes()
        if _sha256(manifest_bytes) != reference.publication.manifest_checksum_sha256:
            raise BundleValidationError("Cached manifest checksum mismatch")
        manifest = KnowledgeBundleManifest.from_bytes(manifest_bytes)
        manifest.require_identity(reference.index)
        for entry in manifest.files:
            path = directory / entry.name
            payload = path.read_bytes()
            if len(payload) != entry.size_bytes or _sha256(payload) != entry.checksum_sha256:
                raise BundleValidationError("Cached bundle file failed integrity check")
        self._validate_faiss(directory, manifest)
        return manifest

    @staticmethod
    def _validate_faiss(
        directory: Path, manifest: KnowledgeBundleManifest
    ) -> None:
        try:
            index, chunks, _meta = load_index_bundle(directory)
        except Exception as exc:
            raise BundleValidationError("FAISS bundle cannot be loaded") from exc
        if index.d != manifest.embedding_dimension:
            raise BundleValidationError("FAISS dimension does not match manifest")
        if index.ntotal != manifest.chunk_count or len(chunks) != manifest.chunk_count:
            raise BundleValidationError("FAISS/chunk count does not match manifest")

    def _evict(self, *, exclude: set[str]) -> None:
        entries = [
            path
            for path in self._root.iterdir()
            if path.is_dir() and path.name != ".locks"
        ]
        total = sum(_directory_size(path) for path in entries)
        for path in sorted(entries, key=lambda value: value.stat().st_mtime):
            if len(entries) <= self._max_entries and total <= self._max_bytes:
                break
            if path.name in exclude:
                continue
            lock_path = self._locks / f"{path.name}.lock"
            try:
                with _file_lock(lock_path, exclusive=True, blocking=False):
                    size = _directory_size(path)
                    shutil.rmtree(path, ignore_errors=True)
                    total -= size
                    entries.remove(path)
                    self._record("cache_eviction", self._monotonic(), "succeeded")
            except BlockingIOError:
                continue

    def _record(self, event: str, started: float, outcome: str) -> None:
        duration_ms = max(0, int((self._monotonic() - started) * 1000))
        self._observe(event, duration_ms, outcome)


class CachedHostedFaissRetriever:
    def __init__(self, cache: VerifiedBundleCache) -> None:
        self._cache = cache
        self._local = LocalFaissRetriever()

    def retrieve(
        self,
        index,
        query: str,
        *,
        top_k: int,
    ) -> list[RetrievalHit]:
        if not isinstance(index, PublishedKnowledgeIndexReference):
            raise TypeError(
                "CachedHostedFaissRetriever requires a published index reference"
            )
        with self._cache.acquire(index) as local:
            return self._local.retrieve(local, query, top_k=top_k)


@contextmanager
def _file_lock(
    path: Path,
    *,
    exclusive: bool,
    blocking: bool = True,
) -> Iterator[BinaryIO]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        if not blocking:
            operation |= fcntl.LOCK_NB
        fcntl.flock(stream.fileno(), operation)
        try:
            yield stream
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
