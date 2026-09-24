"""S3 adapter request-shape tests with no AWS calls."""

from __future__ import annotations

import base64
from datetime import UTC, datetime

import pytest

from app.documents.s3 import S3DocumentStorage, S3DocumentStorageConfig
from app.documents.storage import DocumentObjectNotFound, DocumentStorageError

NOW = datetime(2026, 9, 24, 18, 0, tzinfo=UTC)
CHECKSUM = "a" * 64


class FakeClient:
    def __init__(self) -> None:
        self.presigns = []
        self.head_response = {
            "ContentLength": 42,
            "ContentType": "text/markdown",
            "ChecksumSHA256": base64.b64encode(bytes.fromhex(CHECKSUM)).decode(),
        }
        self.deleted = []

    def generate_presigned_url(
        self, ClientMethod, Params, ExpiresIn, HttpMethod=None
    ):
        self.presigns.append((ClientMethod, Params, ExpiresIn, HttpMethod))
        return f"https://s3.example/{ClientMethod}"

    def head_object(self, **kwargs):
        if isinstance(self.head_response, Exception):
            raise self.head_response
        return self.head_response

    def delete_object(self, **kwargs):
        self.deleted.append(kwargs)
        return {}


class MissingError(Exception):
    response = {"ResponseMetadata": {"HTTPStatusCode": 404}}


def _storage(client=None):
    return S3DocumentStorage(
        client or FakeClient(),
        S3DocumentStorageConfig(
            bucket="private-documents",
            region="eu-west-2",
            kms_key_id="alias/aira-documents",
            endpoint_url="http://s3.test",
        ),
        clock=lambda: NOW,
    )


def test_upload_presign_binds_immutability_checksum_size_type_and_kms() -> None:
    client = FakeClient()
    storage = _storage(client)
    upload = storage.create_presigned_upload(
        "documents/o/w/d/v/source",
        size_bytes=42,
        media_type="text/markdown",
        checksum_sha256=CHECKSUM,
        ttl_seconds=300,
    )

    method, params, ttl, http_method = client.presigns[0]
    assert (method, ttl, http_method) == ("put_object", 300, "PUT")
    assert params["Bucket"] == "private-documents"
    assert params["IfNoneMatch"] == "*"
    assert params["ContentLength"] == 42
    assert params["ChecksumAlgorithm"] == "SHA256"
    assert params["ServerSideEncryption"] == "aws:kms"
    assert params["SSEKMSKeyId"] == "alias/aira-documents"
    assert dict(upload.headers)["if-none-match"] == "*"
    assert upload.expires_at == NOW.replace() + (upload.expires_at - NOW)
    assert (upload.expires_at - NOW).total_seconds() == 300


def test_download_stat_and_delete_are_scoped_to_configured_bucket() -> None:
    client = FakeClient()
    storage = _storage(client)
    download = storage.create_presigned_download(
        "documents/o/w/d/v/source",
        download_filename="runbook.md",
        ttl_seconds=120,
    )
    metadata = storage.stat("documents/o/w/d/v/source")
    storage.delete("documents/o/w/d/v/source")

    assert "runbook.md" in client.presigns[0][1]["ResponseContentDisposition"]
    assert metadata.checksum_sha256 == CHECKSUM
    assert metadata.size_bytes == 42
    assert client.deleted == [
        {"Bucket": "private-documents", "Key": "documents/o/w/d/v/source"}
    ]
    assert (download.expires_at - NOW).total_seconds() == 120


def test_missing_and_malformed_provider_metadata_fail_closed() -> None:
    client = FakeClient()
    client.head_response = MissingError()
    with pytest.raises(DocumentObjectNotFound):
        _storage(client).stat("missing")

    client.head_response = {
        "ContentLength": 42,
        "ContentType": "text/plain",
        "ChecksumSHA256": "not-base64!",
    }
    with pytest.raises(DocumentStorageError, match="checksum"):
        _storage(client).stat("bad")


def test_s3_configuration_requires_kms_and_bounded_retries() -> None:
    with pytest.raises(ValueError, match="kms_key_id"):
        S3DocumentStorageConfig(bucket="bucket", region="region", kms_key_id="")
    with pytest.raises(ValueError, match="max_attempts"):
        S3DocumentStorageConfig(
            bucket="bucket", region="region", kms_key_id="key", max_attempts=0
        )
