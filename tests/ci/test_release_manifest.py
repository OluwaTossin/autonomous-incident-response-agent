from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.deploy.release_manifest import ManifestError, validate_manifest


DIGEST = "sha256:" + "a" * 64
SHA = "b" * 40


def manifest() -> dict[str, object]:
    return {
        "schema_version": 1,
        "git_sha": SHA,
        "terraform_commit": SHA,
        "migration_revision": "9e4b7a2c6d10",
        "workflow_run_id": "1234",
        "source_repository": "OluwaTossin/autonomous-incident-response-agent",
        "source_ref": "refs/heads/main",
        "created_at": "2026-09-26T12:00:00Z",
        "images": {
            service: {
                "repository": f"123456789012.dkr.ecr.eu-west-2.amazonaws.com/aira-prod-{service}",
                "digest": DIGEST,
            }
            for service in ("api", "worker", "web")
        },
    }


def test_valid_release_manifest() -> None:
    validate_manifest(manifest())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("git_sha", "main"),
        ("terraform_commit", "c" * 40),
        ("source_ref", "refs/heads/feature"),
        ("workflow_run_id", "$(whoami)"),
    ],
)
def test_rejects_mutable_or_malformed_provenance(field: str, value: str) -> None:
    data = manifest()
    data[field] = value
    with pytest.raises(ManifestError):
        validate_manifest(data)


def test_rejects_different_api_and_worker_builds() -> None:
    data = manifest()
    data["images"]["worker"]["digest"] = "sha256:" + "c" * 64  # type: ignore[index]
    with pytest.raises(ManifestError, match="same once-built"):
        validate_manifest(data)


def test_requires_successful_development_qualification() -> None:
    data = manifest()
    with pytest.raises(ManifestError, match="not been qualified"):
        validate_manifest(data, require_qualification="development")
    data["qualification"] = {
        "environment": "development",
        "status": "succeeded",
        "workflow_run_id": "4567",
    }
    validate_manifest(data, require_qualification="development")


def test_manifest_is_plain_json_without_secret_fields(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest()), encoding="utf-8")
    content = path.read_text(encoding="utf-8").lower()
    assert "password" not in content
    assert "secret" not in content
    assert "token" not in content
