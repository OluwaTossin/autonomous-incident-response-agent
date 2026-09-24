"""S3-compatible immutable byte storage for hosted knowledge artifacts."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Any, Protocol

from app.documents.s3 import S3DocumentStorageConfig
from app.knowledge.storage import (
    ArtifactNotFound,
    ArtifactObjectMetadata,
    ArtifactStorageError,
    ImmutableArtifactConflict,
)


class StreamingBody(Protocol):
    def read(self) -> bytes: ...


class S3ArtifactClient(Protocol):
    def put_object(self, **kwargs: Any) -> Mapping[str, Any]: ...
    def get_object(self, **kwargs: Any) -> Mapping[str, Any]: ...
    def head_object(self, **kwargs: Any) -> Mapping[str, Any]: ...
    def delete_object(self, **kwargs: Any) -> Mapping[str, Any]: ...


class S3ImmutableObjectStorage:
    def __init__(self, client: S3ArtifactClient, config: S3DocumentStorageConfig) -> None:
        self._client = client
        self._config = config

    def put_immutable(
        self,
        object_key: str,
        payload: bytes,
        *,
        media_type: str,
        checksum_sha256: str,
    ) -> None:
        checksum_base64 = base64.b64encode(bytes.fromhex(checksum_sha256)).decode(
            "ascii"
        )
        try:
            self._client.put_object(
                Bucket=self._config.bucket,
                Key=object_key,
                Body=payload,
                ContentLength=len(payload),
                ContentType=media_type,
                IfNoneMatch="*",
                ChecksumAlgorithm="SHA256",
                ChecksumSHA256=checksum_base64,
                ServerSideEncryption="aws:kms",
                SSEKMSKeyId=self._config.kms_key_id,
            )
            return
        except Exception as exc:
            status = _status(exc)
            if status not in {409, 412}:
                raise ArtifactStorageError("Could not publish immutable object") from exc
        try:
            existing = self.get(object_key)
        except ArtifactStorageError as exc:
            raise ImmutableArtifactConflict(
                "Immutable object collision could not be verified"
            ) from exc
        if existing != payload:
            raise ImmutableArtifactConflict(
                "Immutable object key already contains different bytes"
            )

    def get(self, object_key: str) -> bytes:
        try:
            response = self._client.get_object(
                Bucket=self._config.bucket,
                Key=object_key,
                ChecksumMode="ENABLED",
            )
            body = response["Body"]
            return body.read()
        except Exception as exc:
            if _status(exc) == 404:
                raise ArtifactNotFound("Artifact object does not exist") from exc
            raise ArtifactStorageError("Could not read artifact object") from exc

    def stat(self, object_key: str) -> ArtifactObjectMetadata:
        try:
            response = self._client.head_object(
                Bucket=self._config.bucket,
                Key=object_key,
                ChecksumMode="ENABLED",
            )
        except Exception as exc:
            if _status(exc) == 404:
                raise ArtifactNotFound("Artifact object does not exist") from exc
            raise ArtifactStorageError("Could not inspect artifact object") from exc
        encoded = response.get("ChecksumSHA256")
        checksum = (
            base64.b64decode(encoded).hex() if isinstance(encoded, str) else None
        )
        return ArtifactObjectMetadata(int(response.get("ContentLength", -1)), checksum)

    def delete(self, object_key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._config.bucket, Key=object_key)
        except Exception as exc:
            raise ArtifactStorageError("Could not delete artifact object") from exc


def _status(exc: Exception) -> int | None:
    return getattr(exc, "response", {}).get("ResponseMetadata", {}).get(
        "HTTPStatusCode"
    )
