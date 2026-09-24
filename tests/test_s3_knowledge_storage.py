"""S3 immutable knowledge-artifact adapter tests with an injected fake client."""

from __future__ import annotations

import base64
import hashlib

import pytest

from app.documents.s3 import S3DocumentStorageConfig
from app.knowledge.s3 import S3ImmutableObjectStorage
from app.knowledge.storage import ArtifactNotFound, ImmutableArtifactConflict


class ClientError(Exception):
    def __init__(self, status):
        self.response = {"ResponseMetadata": {"HTTPStatusCode": status}}


class Body:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return self.payload


class Client:
    def __init__(self):
        self.objects = {}
        self.last_put = None

    def put_object(self, **kwargs):
        key = kwargs["Key"]
        if key in self.objects:
            raise ClientError(412)
        self.objects[key] = bytes(kwargs["Body"])
        self.last_put = kwargs
        return {}

    def get_object(self, **kwargs):
        try:
            return {"Body": Body(self.objects[kwargs["Key"]])}
        except KeyError as exc:
            raise ClientError(404) from exc

    def head_object(self, **kwargs):
        try:
            payload = self.objects[kwargs["Key"]]
        except KeyError as exc:
            raise ClientError(404) from exc
        return {
            "ContentLength": len(payload),
            "ChecksumSHA256": base64.b64encode(
                hashlib.sha256(payload).digest()
            ).decode(),
        }

    def delete_object(self, **kwargs):
        self.objects.pop(kwargs["Key"], None)
        return {}


def _storage():
    client = Client()
    config = S3DocumentStorageConfig(
        bucket="private-bucket",
        region="eu-west-2",
        kms_key_id="kms-key",
    )
    return client, S3ImmutableObjectStorage(client, config)


def test_s3_artifact_write_is_conditional_encrypted_and_idempotent() -> None:
    client, storage = _storage()
    payload = b"immutable"
    checksum = hashlib.sha256(payload).hexdigest()

    storage.put_immutable(
        "knowledge-indexes/index/index.faiss",
        payload,
        media_type="application/octet-stream",
        checksum_sha256=checksum,
    )
    storage.put_immutable(
        "knowledge-indexes/index/index.faiss",
        payload,
        media_type="application/octet-stream",
        checksum_sha256=checksum,
    )

    assert client.last_put["IfNoneMatch"] == "*"
    assert client.last_put["ServerSideEncryption"] == "aws:kms"
    assert client.last_put["SSEKMSKeyId"] == "kms-key"
    assert storage.get("knowledge-indexes/index/index.faiss") == payload
    metadata = storage.stat("knowledge-indexes/index/index.faiss")
    assert metadata.size_bytes == len(payload)
    assert metadata.checksum_sha256 == checksum


def test_s3_artifact_collision_and_missing_reads_fail_closed() -> None:
    _, storage = _storage()
    first = b"first"
    storage.put_immutable(
        "key",
        first,
        media_type="application/octet-stream",
        checksum_sha256=hashlib.sha256(first).hexdigest(),
    )
    second = b"second"
    with pytest.raises(ImmutableArtifactConflict):
        storage.put_immutable(
            "key",
            second,
            media_type="application/octet-stream",
            checksum_sha256=hashlib.sha256(second).hexdigest(),
        )
    with pytest.raises(ArtifactNotFound):
        storage.get("missing")
