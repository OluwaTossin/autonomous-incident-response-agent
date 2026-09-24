"""Narrow object-storage contract for hosted document transfers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class DocumentStorageError(Exception):
    """The object provider could not complete an operation."""


class DocumentObjectNotFound(DocumentStorageError):
    """The requested immutable document object does not exist."""


@dataclass(frozen=True, slots=True)
class PresignedUpload:
    url: str
    method: str
    headers: tuple[tuple[str, str], ...]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PresignedDownload:
    url: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class StoredObjectMetadata:
    size_bytes: int
    media_type: str
    checksum_sha256: str | None


class DocumentObjectStorage(Protocol):
    def create_presigned_upload(
        self,
        object_key: str,
        *,
        size_bytes: int,
        media_type: str,
        checksum_sha256: str,
        ttl_seconds: int,
    ) -> PresignedUpload: ...

    def create_presigned_download(
        self,
        object_key: str,
        *,
        download_filename: str,
        ttl_seconds: int,
    ) -> PresignedDownload: ...

    def stat(self, object_key: str) -> StoredObjectMetadata: ...

    def delete(self, object_key: str) -> None: ...

