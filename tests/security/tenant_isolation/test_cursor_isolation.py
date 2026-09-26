"""Adversarial cursor tampering and tenant-scope replay tests."""

from __future__ import annotations

import base64
import json

import pytest

from app.security.cursors import CursorCodec, InvalidCursor

CODEC = CursorCodec("test-cursor-signing-key-at-least-32-bytes")
ORG_A = {"organization_id": "org-a", "workspace_id": "workspace-a1"}
ORG_B = {"organization_id": "org-b", "workspace_id": "workspace-b1"}


def _replace_payload(token: str, field: str, value: str) -> str:
    payload_token, signature = token.split(".", 1)
    payload = json.loads(
        base64.urlsafe_b64decode(payload_token + "=" * (-len(payload_token) % 4))
    )
    payload["values"][field] = value
    modified = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    return f"{modified}.{signature}"


def test_cursor_is_bound_to_kind_and_tenant_scope() -> None:
    token = CODEC.encode(
        kind="incidents",
        scope=ORG_A,
        values={"created_at": "2026-09-25T12:00:00+00:00", "id": "incident-a"},
    )

    assert CODEC.decode(token, kind="incidents", scope=ORG_A)["id"] == "incident-a"
    with pytest.raises(InvalidCursor):
        CODEC.decode(token, kind="incidents", scope=ORG_B)
    with pytest.raises(InvalidCursor):
        CODEC.decode(token, kind="triage-runs", scope=ORG_A)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("created_at", "2030-01-01T00:00:00+00:00"),
        ("id", "foreign-resource-id"),
    ],
)
def test_modified_cursor_values_are_rejected(field: str, value: str) -> None:
    token = CODEC.encode(
        kind="incidents",
        scope=ORG_A,
        values={"created_at": "2026-09-25T12:00:00+00:00", "id": "incident-a"},
    )

    with pytest.raises(InvalidCursor):
        CODEC.decode(_replace_payload(token, field, value), kind="incidents", scope=ORG_A)
