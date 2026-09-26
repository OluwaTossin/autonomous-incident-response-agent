"""Tamper-evident pagination cursors bound to an authorized tenant scope."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from collections.abc import Mapping


class InvalidCursor(ValueError):
    """A cursor is malformed, modified, or belongs to another scope."""


class CursorCodec:
    """Sign opaque cursor payloads without making cursor data authoritative."""

    def __init__(self, signing_key: str) -> None:
        key = signing_key.encode("utf-8")
        if len(key) < 32:
            raise ValueError("Cursor signing key must be at least 32 bytes")
        self._key = key

    def encode(
        self,
        *,
        kind: str,
        scope: Mapping[str, str],
        values: Mapping[str, str],
    ) -> str:
        payload = json.dumps(
            {
                "version": 1,
                "kind": kind,
                "scope": dict(sorted(scope.items())),
                "values": dict(sorted(values.items())),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        signature = hmac.digest(self._key, payload, hashlib.sha256)
        return f"{_encode(payload)}.{_encode(signature)}"

    def decode(
        self,
        value: str,
        *,
        kind: str,
        scope: Mapping[str, str],
    ) -> dict[str, str]:
        try:
            if len(value) > 1024:
                raise InvalidCursor
            payload_token, signature_token = value.split(".", 1)
            payload = _decode(payload_token)
            signature = _decode(signature_token)
            expected = hmac.digest(self._key, payload, hashlib.sha256)
            if not hmac.compare_digest(signature, expected):
                raise InvalidCursor
            decoded = json.loads(payload)
            if (
                decoded.get("version") != 1
                or decoded.get("kind") != kind
                or decoded.get("scope") != dict(sorted(scope.items()))
                or not isinstance(decoded.get("values"), dict)
                or not all(
                    isinstance(key, str) and isinstance(item, str)
                    for key, item in decoded["values"].items()
                )
            ):
                raise InvalidCursor
            return decoded["values"]
        except (
            ValueError,
            TypeError,
            UnicodeDecodeError,
            binascii.Error,
            json.JSONDecodeError,
        ) as exc:
            raise InvalidCursor("Invalid pagination cursor") from exc


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
