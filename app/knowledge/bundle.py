"""Versioned immutable hosted FAISS bundle construction and validation."""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import faiss
import numpy as np

from app.authorization.service import AuthorizedTenantContext
from app.knowledge.contracts import (
    HostedKnowledgeIndexReference,
    KnowledgeSourceReference,
)
from app.rag.chunking import TextChunk, chunk_documents
from app.rag.embeddings import embed_texts
from app.rag.index_store import build_index
from app.rag.loader import SourceDocument

BUNDLE_SCHEMA_VERSION = 1
BUNDLE_FORMAT_VERSION = "aira-faiss-v1"
INDEX_FILENAME = "index.faiss"
CHUNKS_FILENAME = "chunks.jsonl"
MANIFEST_FILENAME = "manifest.json"
SIMILARITY_SEMANTICS = "cosine_via_l2_normalized_inner_product"
CHUNKING_ALGORITHM = "character_window"
CHUNKING_VERSION = 1


class BundleValidationError(ValueError):
    """Bundle metadata or bytes fail compatibility or integrity validation."""


class KnowledgeSourceContentReader(Protocol):
    def read(
        self,
        context: AuthorizedTenantContext,
        source: KnowledgeSourceReference,
    ) -> bytes: ...


@dataclass(frozen=True, slots=True)
class BundleFile:
    name: str
    size_bytes: int
    checksum_sha256: str


@dataclass(frozen=True, slots=True)
class BundleSource:
    origin: str
    source: str
    category: str
    document_id: str | None
    document_version_id: str | None
    system_source_id: str | None
    checksum_sha256: str | None


@dataclass(frozen=True, slots=True)
class KnowledgeBundleManifest:
    schema_version: int
    format_version: str
    knowledge_index_version_id: str
    organization_id: str
    workspace_id: str
    created_at: str
    embedding_model: str
    embedding_dimension: int
    similarity_semantics: str
    chunking_algorithm: str
    chunking_version: int
    chunk_size: int
    chunk_overlap: int
    chunk_count: int
    sources: tuple[BundleSource, ...]
    files: tuple[BundleFile, ...]

    def __post_init__(self) -> None:
        if self.schema_version != BUNDLE_SCHEMA_VERSION:
            raise BundleValidationError("Unsupported bundle manifest schema")
        if self.format_version != BUNDLE_FORMAT_VERSION:
            raise BundleValidationError("Unsupported FAISS bundle format")
        if self.embedding_dimension < 1 or self.chunk_count < 1:
            raise BundleValidationError("Bundle dimension and chunk count must be positive")
        if self.chunk_size < 1 or not 0 <= self.chunk_overlap < self.chunk_size:
            raise BundleValidationError("Invalid chunking configuration")
        if self.similarity_semantics != SIMILARITY_SEMANTICS:
            raise BundleValidationError("Unsupported similarity semantics")
        names = {entry.name for entry in self.files}
        if names != {INDEX_FILENAME, CHUNKS_FILENAME}:
            raise BundleValidationError("Bundle must contain index.faiss and chunks.jsonl")
        for entry in self.files:
            if entry.size_bytes < 0 or not _is_sha256(entry.checksum_sha256):
                raise BundleValidationError("Invalid bundle file integrity metadata")
        try:
            created_at = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise BundleValidationError("Invalid manifest created_at") from exc
        if created_at.tzinfo is None:
            raise BundleValidationError("Manifest created_at must be timezone-aware")

    def file(self, name: str) -> BundleFile:
        for entry in self.files:
            if entry.name == name:
                return entry
        raise BundleValidationError(f"Missing bundle file metadata: {name}")

    def to_bytes(self) -> bytes:
        return (
            json.dumps(asdict(self), sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")

    @classmethod
    def from_bytes(cls, payload: bytes) -> KnowledgeBundleManifest:
        try:
            raw = json.loads(payload.decode("utf-8"))
            if not isinstance(raw, dict):
                raise TypeError
            raw["sources"] = tuple(BundleSource(**row) for row in raw["sources"])
            raw["files"] = tuple(BundleFile(**row) for row in raw["files"])
            return cls(**raw)
        except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BundleValidationError("Invalid bundle manifest") from exc

    def require_identity(self, reference: HostedKnowledgeIndexReference) -> None:
        if (
            self.knowledge_index_version_id != str(reference.index_version_id)
            or self.organization_id != str(reference.scope.organization_id)
            or self.workspace_id != str(reference.scope.workspace_id)
        ):
            raise BundleValidationError("Bundle identity does not match authorized index")
        manifest_versions = {
            source.document_version_id
            for source in self.sources
            if source.document_version_id is not None
        }
        if manifest_versions != {str(value) for value in reference.source_document_versions}:
            raise BundleValidationError("Bundle source versions do not match index metadata")


@dataclass(frozen=True, slots=True)
class BuiltKnowledgeBundle:
    directory: Path
    manifest: KnowledgeBundleManifest
    manifest_bytes: bytes
    manifest_checksum_sha256: str

    def file_bytes(self, name: str) -> bytes:
        return (self.directory / name).read_bytes()


class HostedKnowledgeBundleBuilder:
    def __init__(
        self,
        content_reader: KnowledgeSourceContentReader,
        *,
        embedding_model: str,
        chunk_size: int = 900,
        chunk_overlap: int = 150,
        batch_size: int = 64,
        embedder: Callable[..., np.ndarray] = embed_texts,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        temp_root: Path | None = None,
    ) -> None:
        if not embedding_model.strip():
            raise ValueError("Embedding model cannot be blank")
        if chunk_size < 1 or not 0 <= chunk_overlap < chunk_size:
            raise ValueError("Invalid chunking configuration")
        if batch_size < 1:
            raise ValueError("Embedding batch size must be positive")
        self._reader = content_reader
        self._embedding_model = embedding_model
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._batch_size = batch_size
        self._embedder = embedder
        self._clock = clock
        self._temp_root = temp_root
        if self._temp_root is not None:
            self._temp_root.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def build(
        self,
        context: AuthorizedTenantContext,
        reference: HostedKnowledgeIndexReference,
        sources: Sequence[KnowledgeSourceReference],
    ) -> Iterator[BuiltKnowledgeBundle]:
        if not sources:
            raise BundleValidationError("Cannot build an empty knowledge bundle")
        _require_context_scope(context, reference)
        with tempfile.TemporaryDirectory(
            prefix="aira-index-build-",
            dir=self._temp_root,
        ) as temporary:
            directory = Path(temporary)
            chunks = self._build_chunks(context, reference, sources)
            if not chunks:
                raise BundleValidationError("Knowledge sources produced no text chunks")
            vectors = self._embedder(
                [chunk.text for chunk in chunks],
                batch_size=self._batch_size,
                model=self._embedding_model,
            )
            index = build_index(vectors)
            faiss.write_index(index, str(directory / INDEX_FILENAME))
            _write_chunks(directory / CHUNKS_FILENAME, chunks)
            files = tuple(
                _file_metadata(directory / name)
                for name in (INDEX_FILENAME, CHUNKS_FILENAME)
            )
            manifest = KnowledgeBundleManifest(
                schema_version=BUNDLE_SCHEMA_VERSION,
                format_version=BUNDLE_FORMAT_VERSION,
                knowledge_index_version_id=str(reference.index_version_id),
                organization_id=str(reference.scope.organization_id),
                workspace_id=str(reference.scope.workspace_id),
                created_at=self._clock().isoformat(),
                embedding_model=self._embedding_model,
                embedding_dimension=index.d,
                similarity_semantics=SIMILARITY_SEMANTICS,
                chunking_algorithm=CHUNKING_ALGORITHM,
                chunking_version=CHUNKING_VERSION,
                chunk_size=self._chunk_size,
                chunk_overlap=self._chunk_overlap,
                chunk_count=len(chunks),
                sources=tuple(_manifest_source(source) for source in sources),
                files=files,
            )
            manifest.require_identity(reference)
            manifest_bytes = manifest.to_bytes()
            yield BuiltKnowledgeBundle(
                directory=directory,
                manifest=manifest,
                manifest_bytes=manifest_bytes,
                manifest_checksum_sha256=_sha256(manifest_bytes),
            )

    def _build_chunks(
        self,
        context: AuthorizedTenantContext,
        reference: HostedKnowledgeIndexReference,
        sources: Sequence[KnowledgeSourceReference],
    ) -> list[TextChunk]:
        chunks: list[TextChunk] = []
        for source in sources:
            payload = self._reader.read(context, source)
            text = payload.decode("utf-8", errors="replace")
            if not text.strip():
                continue
            plain = chunk_documents(
                [SourceDocument(text, source.source, source.category)],
                chunk_size=self._chunk_size,
                chunk_overlap=self._chunk_overlap,
            )
            for chunk in plain:
                chunks.append(
                    TextChunk(
                        text=chunk.text,
                        source=chunk.source,
                        doc_type=chunk.doc_type,
                        chunk_index=chunk.chunk_index,
                        origin=source.origin.value,
                        organization_id=(
                            str(source.scope.organization_id) if source.scope else None
                        ),
                        workspace_id=(
                            str(source.scope.workspace_id) if source.scope else None
                        ),
                        document_id=(
                            str(source.document_id) if source.document_id else None
                        ),
                        document_version_id=(
                            str(source.document_version_id)
                            if source.document_version_id
                            else None
                        ),
                        knowledge_index_version_id=str(reference.index_version_id),
                    )
                )
        return chunks


def artifact_prefix(reference: HostedKnowledgeIndexReference) -> str:
    return (
        f"knowledge-indexes/{reference.scope.organization_id}/"
        f"{reference.scope.workspace_id}/{reference.index_version_id}/"
    )


def _manifest_source(source: KnowledgeSourceReference) -> BundleSource:
    return BundleSource(
        origin=source.origin.value,
        source=source.source,
        category=source.category,
        document_id=str(source.document_id) if source.document_id else None,
        document_version_id=(
            str(source.document_version_id) if source.document_version_id else None
        ),
        system_source_id=source.system_source_id,
        checksum_sha256=source.checksum_sha256,
    )


def _write_chunks(path: Path, chunks: Sequence[TextChunk]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for chunk in chunks:
            row = {key: value for key, value in asdict(chunk).items() if value is not None}
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def _file_metadata(path: Path) -> BundleFile:
    payload = path.read_bytes()
    return BundleFile(path.name, len(payload), _sha256(payload))


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _require_context_scope(
    context: AuthorizedTenantContext,
    reference: HostedKnowledgeIndexReference,
) -> None:
    if (
        context.workspace_id is None
        or context.organization_id != reference.scope.organization_id
        or context.workspace_id != reference.scope.workspace_id
    ):
        raise BundleValidationError("Authorized context does not match bundle scope")
