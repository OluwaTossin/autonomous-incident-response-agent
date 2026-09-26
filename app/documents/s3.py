"""S3-compatible hosted document object-storage adapter."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from app.documents.storage import (
    DocumentObjectNotFound,
    DocumentStorageError,
    PresignedDownload,
    PresignedUpload,
    StoredObjectMetadata,
)


class S3Client(Protocol):
    def generate_presigned_url(
        self,
        ClientMethod: str,
        Params: Mapping[str, Any],
        ExpiresIn: int,
        HttpMethod: str | None = None,
    ) -> str: ...

    def head_object(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def delete_object(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def put_object(self, **kwargs: Any) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class S3DocumentStorageConfig:
    bucket: str
    region: str
    kms_key_id: str
    endpoint_url: str | None = None
    connect_timeout_seconds: float = 2.0
    read_timeout_seconds: float = 5.0
    max_attempts: int = 3

    def __post_init__(self) -> None:
        for field_name in ("bucket", "region", "kms_key_id"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"S3 {field_name} cannot be blank")
        if self.connect_timeout_seconds <= 0 or self.read_timeout_seconds <= 0:
            raise ValueError("S3 timeouts must be positive")
        if self.max_attempts < 1:
            raise ValueError("S3 max_attempts must be positive")


def create_s3_client(config: S3DocumentStorageConfig) -> S3Client:
    """Create one bounded client at a composition root, never as module state."""
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        region_name=config.region,
        endpoint_url=config.endpoint_url,
        config=Config(
            connect_timeout=config.connect_timeout_seconds,
            read_timeout=config.read_timeout_seconds,
            retries={"max_attempts": config.max_attempts, "mode": "standard"},
        ),
    )


class S3DocumentStorage:
    def __init__(
        self,
        client: S3Client,
        config: S3DocumentStorageConfig,
        *,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._client = client
        self._config = config
        self._clock = clock

    def create_presigned_upload(
        self,
        object_key: str,
        *,
        size_bytes: int,
        media_type: str,
        checksum_sha256: str,
        ttl_seconds: int,
    ) -> PresignedUpload:
        checksum_base64 = base64.b64encode(bytes.fromhex(checksum_sha256)).decode(
            "ascii"
        )
        headers = {
            "content-type": media_type,
            "content-length": str(size_bytes),
            "if-none-match": "*",
            "x-amz-checksum-algorithm": "SHA256",
            "x-amz-checksum-sha256": checksum_base64,
            "x-amz-server-side-encryption": "aws:kms",
            "x-amz-server-side-encryption-aws-kms-key-id": self._config.kms_key_id,
        }
        params: dict[str, Any] = {
            "Bucket": self._config.bucket,
            "Key": object_key,
            "ContentType": media_type,
            "ContentLength": size_bytes,
            "IfNoneMatch": "*",
            "ChecksumAlgorithm": "SHA256",
            "ChecksumSHA256": checksum_base64,
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": self._config.kms_key_id,
        }
        try:
            url = self._client.generate_presigned_url(
                "put_object",
                Params=params,
                ExpiresIn=ttl_seconds,
                HttpMethod="PUT",
            )
        except Exception as exc:
            raise DocumentStorageError("Could not create document upload") from exc
        return PresignedUpload(
            url=url,
            method="PUT",
            headers=tuple(sorted(headers.items())),
            expires_at=self._clock() + timedelta(seconds=ttl_seconds),
        )

    def create_presigned_download(
        self,
        object_key: str,
        *,
        download_filename: str,
        ttl_seconds: int,
    ) -> PresignedDownload:
        safe_name = download_filename.replace('"', "")
        try:
            url = self._client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self._config.bucket,
                    "Key": object_key,
                    "ResponseContentDisposition": (
                        f'attachment; filename="{safe_name}"'
                    ),
                },
                ExpiresIn=ttl_seconds,
                HttpMethod="GET",
            )
        except Exception as exc:
            raise DocumentStorageError("Could not create document download") from exc
        return PresignedDownload(
            url=url,
            expires_at=self._clock() + timedelta(seconds=ttl_seconds),
        )

    def stat(self, object_key: str) -> StoredObjectMetadata:
        try:
            response = self._client.head_object(
                Bucket=self._config.bucket,
                Key=object_key,
                ChecksumMode="ENABLED",
            )
        except Exception as exc:
            status = getattr(exc, "response", {}).get("ResponseMetadata", {}).get(
                "HTTPStatusCode"
            )
            if status == 404:
                raise DocumentObjectNotFound("Document object does not exist") from exc
            raise DocumentStorageError("Could not inspect document object") from exc
        checksum = response.get("ChecksumSHA256")
        checksum_hex = None
        if checksum:
            try:
                checksum_hex = base64.b64decode(str(checksum), validate=True).hex()
            except ValueError as exc:
                raise DocumentStorageError(
                    "Document object returned an invalid checksum"
                ) from exc
        return StoredObjectMetadata(
            size_bytes=int(response["ContentLength"]),
            media_type=str(response.get("ContentType") or ""),
            checksum_sha256=checksum_hex,
        )

    def delete(self, object_key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._config.bucket, Key=object_key)
        except Exception as exc:
            raise DocumentStorageError("Could not delete document object") from exc

    def put_immutable(
        self,
        object_key: str,
        content: bytes,
        *,
        media_type: str,
        checksum_sha256: str,
    ) -> StoredObjectMetadata:
        """Write a verified migration object without exposing a browser upload URL."""
        checksum_base64 = base64.b64encode(bytes.fromhex(checksum_sha256)).decode(
            "ascii"
        )
        try:
            self._client.put_object(
                Bucket=self._config.bucket,
                Key=object_key,
                Body=content,
                ContentLength=len(content),
                ContentType=media_type,
                IfNoneMatch="*",
                ChecksumAlgorithm="SHA256",
                ChecksumSHA256=checksum_base64,
                ServerSideEncryption="aws:kms",
                SSEKMSKeyId=self._config.kms_key_id,
            )
        except Exception as exc:
            raise DocumentStorageError("Could not store migration document") from exc
        return self.stat(object_key)
