#!/usr/bin/env python3
"""Create, validate, qualify, and expose immutable hosted release manifests."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{4,64}$")
ECR_REPOSITORY_RE = re.compile(
    r"^[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/"
    r"[a-z0-9]+(?:[._/-][a-z0-9]+)*$"
)
SERVICES = ("api", "worker", "web")


class ManifestError(ValueError):
    """Raised when release provenance is incomplete or malformed."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"Unable to read release manifest: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError("Release manifest must be a JSON object")
    return data


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _required_string(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{field} must be a non-empty string")
    return value


def validate_manifest(
    data: dict[str, Any],
    *,
    expected_repository: str | None = None,
    expected_images: dict[str, str] | None = None,
    require_qualification: str | None = None,
) -> None:
    if data.get("schema_version") != 1:
        raise ManifestError("schema_version must be 1")
    git_sha = _required_string(data, "git_sha")
    terraform_commit = _required_string(data, "terraform_commit")
    migration_revision = _required_string(data, "migration_revision")
    workflow_run_id = _required_string(data, "workflow_run_id")
    source_repository = _required_string(data, "source_repository")
    source_ref = _required_string(data, "source_ref")
    _required_string(data, "created_at")
    if not SHA_RE.fullmatch(git_sha) or not SHA_RE.fullmatch(terraform_commit):
        raise ManifestError("git_sha and terraform_commit must be 40 lowercase hex characters")
    if git_sha != terraform_commit:
        raise ManifestError("Terraform and application source must use the same commit")
    if not REVISION_RE.fullmatch(migration_revision):
        raise ManifestError("migration_revision must be a lowercase Alembic revision")
    if not workflow_run_id.isdigit():
        raise ManifestError("workflow_run_id must be numeric")
    if source_ref != "refs/heads/main":
        raise ManifestError("release source_ref must be refs/heads/main")
    if expected_repository and source_repository != expected_repository:
        raise ManifestError("release source repository does not match this repository")

    images = data.get("images")
    if not isinstance(images, dict) or set(images) != set(SERVICES):
        raise ManifestError("images must contain exactly api, worker, and web")
    for service in SERVICES:
        image = images.get(service)
        if not isinstance(image, dict):
            raise ManifestError(f"images.{service} must be an object")
        repository = _required_string(image, "repository")
        digest = _required_string(image, "digest")
        if not ECR_REPOSITORY_RE.fullmatch(repository):
            raise ManifestError(f"images.{service}.repository must be a private ECR repository")
        if not DIGEST_RE.fullmatch(digest):
            raise ManifestError(f"images.{service}.digest must be an immutable sha256 digest")
        if expected_images and repository != expected_images.get(service):
            raise ManifestError(f"images.{service}.repository is not the approved release repository")
    if images["api"]["digest"] != images["worker"]["digest"]:
        raise ManifestError("API and worker must use the same once-built hosted Python image")

    if require_qualification:
        qualification = data.get("qualification")
        if not isinstance(qualification, dict):
            raise ManifestError("release has not been qualified")
        if qualification.get("environment") != require_qualification:
            raise ManifestError(
                f"release must be qualified in {require_qualification}, not "
                f"{qualification.get('environment')!r}"
            )
        if qualification.get("status") != "succeeded":
            raise ManifestError("release qualification did not succeed")
        run_id = qualification.get("workflow_run_id")
        if not isinstance(run_id, str) or not run_id.isdigit():
            raise ManifestError("qualification workflow_run_id must be numeric")


def _images(values: list[str]) -> dict[str, dict[str, str]]:
    parsed: dict[str, dict[str, str]] = {}
    for value in values:
        try:
            service, repository, digest = value.split("=", 2)
        except ValueError as exc:
            raise ManifestError("--image must be SERVICE=REPOSITORY=DIGEST") from exc
        if service in parsed:
            raise ManifestError(f"duplicate image service: {service}")
        parsed[service] = {"repository": repository, "digest": digest}
    return parsed


def _expected_images(values: list[str]) -> dict[str, str]:
    expected: dict[str, str] = {}
    for value in values:
        try:
            service, repository = value.split("=", 1)
        except ValueError as exc:
            raise ManifestError("--expected-image must be SERVICE=REPOSITORY") from exc
        expected[service] = repository
    return expected


def command_create(args: argparse.Namespace) -> None:
    data = {
        "schema_version": 1,
        "git_sha": args.git_sha,
        "terraform_commit": args.git_sha,
        "migration_revision": args.migration_revision,
        "workflow_run_id": args.workflow_run_id,
        "source_repository": args.source_repository,
        "source_ref": args.source_ref,
        "created_at": args.created_at or _utc_now(),
        "images": _images(args.image),
    }
    validate_manifest(data, expected_repository=args.source_repository)
    _write(args.output, data)


def command_validate(args: argparse.Namespace) -> None:
    data = _read(args.manifest)
    expected = _expected_images(args.expected_image) if args.expected_image else None
    validate_manifest(
        data,
        expected_repository=args.expected_repository,
        expected_images=expected,
        require_qualification=args.require_qualification,
    )


def command_qualify(args: argparse.Namespace) -> None:
    data = _read(args.manifest)
    validate_manifest(data, expected_repository=args.expected_repository)
    previous = data.get("qualification")
    if previous is not None:
        history = data.setdefault("qualification_history", [])
        if not isinstance(history, list) or not isinstance(previous, dict):
            raise ManifestError("qualification history is malformed")
        history.append(previous)
    data["qualification"] = {
        "environment": args.environment,
        "status": "succeeded",
        "workflow_run_id": args.workflow_run_id,
        "qualified_at": args.qualified_at or _utc_now(),
        "terraform_state_serial": args.terraform_state_serial,
    }
    validate_manifest(data, require_qualification=args.environment)
    _write(args.output, data)


def command_outputs(args: argparse.Namespace) -> None:
    data = _read(args.manifest)
    expected = _expected_images(args.expected_image) if args.expected_image else None
    validate_manifest(
        data,
        expected_repository=args.expected_repository,
        expected_images=expected,
        require_qualification=args.require_qualification,
    )
    output_value = args.output or os.environ.get("GITHUB_OUTPUT", "")
    if not output_value:
        raise ManifestError("GITHUB_OUTPUT or --output is required")
    output_path = Path(output_value)
    values = {
        "git_sha": data["git_sha"],
        "migration_revision": data["migration_revision"],
        **{
            f"{service}_{field}": data["images"][service][field]
            for service in SERVICES
            for field in ("repository", "digest")
        },
    }
    with output_path.open("a", encoding="utf-8") as stream:
        for key, value in values.items():
            stream.write(f"{key}={value}\n")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create")
    create.add_argument("--git-sha", required=True)
    create.add_argument("--migration-revision", required=True)
    create.add_argument("--workflow-run-id", required=True)
    create.add_argument("--source-repository", required=True)
    create.add_argument("--source-ref", required=True)
    create.add_argument("--created-at")
    create.add_argument("--image", action="append", required=True)
    create.add_argument("--output", type=Path, required=True)
    create.set_defaults(handler=command_create)

    validate = commands.add_parser("validate")
    validate.add_argument("manifest", type=Path)
    validate.add_argument("--expected-repository")
    validate.add_argument("--expected-image", action="append", default=[])
    validate.add_argument("--require-qualification", choices=("development", "production"))
    validate.set_defaults(handler=command_validate)

    qualify = commands.add_parser("qualify")
    qualify.add_argument("manifest", type=Path)
    qualify.add_argument("--environment", choices=("development", "production"), required=True)
    qualify.add_argument("--workflow-run-id", required=True)
    qualify.add_argument("--terraform-state-serial", type=int, required=True)
    qualify.add_argument("--expected-repository")
    qualify.add_argument("--qualified-at")
    qualify.add_argument("--output", type=Path, required=True)
    qualify.set_defaults(handler=command_qualify)

    outputs = commands.add_parser("outputs")
    outputs.add_argument("manifest", type=Path)
    outputs.add_argument("--expected-repository")
    outputs.add_argument("--expected-image", action="append", default=[])
    outputs.add_argument("--require-qualification", choices=("development", "production"))
    outputs.add_argument("--output")
    outputs.set_defaults(handler=command_outputs)
    return root


def main() -> None:
    args = parser().parse_args()
    try:
        args.handler(args)
    except ManifestError as exc:
        raise SystemExit(f"release manifest rejected: {exc}") from exc


if __name__ == "__main__":
    main()
