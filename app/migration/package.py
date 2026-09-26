"""Versioned, checksummed migration packages built from read-only V2 workspaces."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

MIGRATION_SCHEMA_VERSION = 1
MIGRATION_TOOL_VERSION = "3.27"
MANIFEST_NAME = "migration-manifest.json"

_DOCUMENT_DIRECTORIES = {
    "runbooks": "runbook",
    "incidents": "incident",
    "logs": "log",
    "knowledge_base": "knowledge",
}
_HISTORY_FILENAMES = {
    "triage_outputs.jsonl",
    "triage_feedback.jsonl",
    "n8n_workflow_runs.jsonl",
}
_MEDIA_TYPES = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".log": "text/plain",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
}
_CONFIG_ALLOWLIST = frozenset(
    {
        "rag_top_k",
        "retrieval_top_k",
        "severity_threshold",
        "escalation_threshold",
    }
)
_SECRET_KEY_RE = re.compile(
    r"(?:api[_-]?key|secret|password|passwd|token|credential|private[_-]?key|"
    r"access[_-]?key)",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(
    r"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|"
    r"(?:bearer|authorization)\s+[A-Za-z0-9._~+/=-]{12,})",
    re.IGNORECASE,
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?im)^\s*(?:[A-Z0-9_]*(?:API_KEY|SECRET|PASSWORD|TOKEN|PRIVATE_KEY|"
    r"ACCESS_KEY)[A-Z0-9_]*)\s*[:=]\s*[\"']?(?!<|\$\{|REDACTED|CHANGE[-_ ]?ME)"
    r"[^\s\"']{8,}"
)
_SAFE_FILENAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,254}$")


class MigrationPackageError(ValueError):
    """A migration package is unsafe, corrupt, or unsupported."""

    def __init__(self, category: str, message: str) -> None:
        self.category = category
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class MigrationLimits:
    max_files: int = 2_000
    max_file_bytes: int = 5_242_880
    max_total_bytes: int = 524_288_000
    max_metadata_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        if min(
            self.max_files,
            self.max_file_bytes,
            self.max_total_bytes,
            self.max_metadata_bytes,
        ) < 1:
            raise ValueError("Migration package limits must be positive")


@dataclass(frozen=True, slots=True)
class MigrationRecord:
    source_id: str
    record_type: str
    package_path: str
    source_path: str
    checksum_sha256: str
    size_bytes: int
    media_type: str
    category: str | None = None


@dataclass(frozen=True, slots=True)
class MigrationManifest:
    schema_version: int
    source_version: str
    source_type: str
    source_identifier: str
    created_at: datetime
    migration_tool_version: str
    records: tuple[MigrationRecord, ...]
    counts: tuple[tuple[str, int], ...]
    source_build_sha: str | None = None
    workspace_config: tuple[tuple[str, Any], ...] = ()
    omitted: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LoadedMigrationPackage:
    root: Path
    manifest: MigrationManifest
    manifest_hash: str

    @property
    def documents(self) -> tuple[MigrationRecord, ...]:
        return tuple(
            record for record in self.manifest.records if record.record_type == "document"
        )


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def source_record_id(
    source_identifier: str, source_path: str, checksum_sha256: str
) -> str:
    material = f"aira-v2\0{source_identifier}\0{source_path}\0{checksum_sha256}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def export_v2_workspace(
    source: Path,
    destination: Path,
    *,
    source_identifier: str | None = None,
    source_build_sha: str | None = None,
    limits: MigrationLimits = MigrationLimits(),
    created_at: datetime | None = None,
) -> LoadedMigrationPackage:
    """Copy supported V2 artifacts into a separate immutable-input package."""
    source = source.resolve(strict=True)
    destination = destination.resolve()
    if not source.is_dir():
        raise MigrationPackageError("invalid_record", "V2 source must be a directory")
    if destination == source or source in destination.parents:
        raise MigrationPackageError(
            "invalid_record", "Migration package must be outside the V2 source"
        )
    if destination.exists() and any(destination.iterdir()):
        raise MigrationPackageError(
            "conflict", "Migration package destination must be empty"
        )
    destination.mkdir(parents=True, exist_ok=True)

    identifier = _bounded_text(source_identifier or source.name, "source identifier")
    records: list[MigrationRecord] = []
    total_bytes = 0
    data_root = source / "data"
    for directory_name, category in _DOCUMENT_DIRECTORIES.items():
        directory = data_root / directory_name
        if not directory.exists():
            continue
        for candidate in sorted(directory.rglob("*")):
            if candidate.is_symlink():
                raise MigrationPackageError(
                    "invalid_record", "V2 source contains an unsafe file"
                )
            if candidate.is_dir():
                continue
            _require_safe_source_file(candidate, source)
            if candidate.name in _HISTORY_FILENAMES:
                continue
            media_type = _media_type(candidate)
            if media_type is None:
                continue
            content = _read_bounded(candidate, limits.max_file_bytes)
            _reject_secret_content(content)
            total_bytes += len(content)
            _check_package_limits(len(records) + 1, total_bytes, limits)
            source_path = candidate.relative_to(source).as_posix()
            checksum = sha256_bytes(content)
            package_path = f"documents/{source_path}"
            target = _safe_join(destination, package_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            records.append(
                MigrationRecord(
                    source_id=source_record_id(identifier, source_path, checksum),
                    record_type="document",
                    package_path=package_path,
                    source_path=source_path,
                    checksum_sha256=checksum,
                    size_bytes=len(content),
                    media_type=media_type,
                    category=category,
                )
            )

    for filename in sorted(_HISTORY_FILENAMES):
        candidate = data_root / "logs" / filename
        if not candidate.exists():
            continue
        _require_safe_source_file(candidate, source)
        content = _read_bounded(candidate, limits.max_file_bytes)
        total_bytes += len(content)
        _check_package_limits(len(records) + 1, total_bytes, limits)
        source_path = candidate.relative_to(source).as_posix()
        checksum = sha256_bytes(content)
        package_path = f"history/{filename}"
        target = _safe_join(destination, package_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        records.append(
            MigrationRecord(
                source_id=source_record_id(identifier, source_path, checksum),
                record_type="historical_only",
                package_path=package_path,
                source_path=source_path,
                checksum_sha256=checksum,
                size_bytes=len(content),
                media_type="application/x-ndjson",
            )
        )

    workspace_config, omitted = _read_workspace_config(source, limits)
    counts = _record_counts(records)
    manifest_data: dict[str, Any] = {
        "schema_version": MIGRATION_SCHEMA_VERSION,
        "source_version": "2",
        "source_type": "aira-v2-workspace",
        "source_identifier": identifier,
        "created_at": (created_at or datetime.now(UTC)).isoformat(),
        "migration_tool_version": MIGRATION_TOOL_VERSION,
        "source_build_sha": source_build_sha,
        "counts": counts,
        "workspace_config": workspace_config,
        "omitted": sorted(
            {
                "local_faiss_index:rebuild_required",
                "sessions_and_api_keys:not_exported",
                "secrets:not_exported",
                *omitted,
            }
        ),
        "records": [_record_json(record) for record in records],
    }
    manifest_bytes = _canonical_json(manifest_data)
    if len(manifest_bytes) > limits.max_metadata_bytes:
        raise MigrationPackageError("invalid_manifest", "Manifest is too large")
    (destination / MANIFEST_NAME).write_bytes(manifest_bytes)
    return load_migration_package(destination, limits=limits)


def load_migration_package(
    root: Path, *, limits: MigrationLimits = MigrationLimits()
) -> LoadedMigrationPackage:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise MigrationPackageError(
            "invalid_manifest", "Only directory migration packages are supported"
        )
    package_files = _validate_package_tree(root, limits)
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise MigrationPackageError("invalid_manifest", "Manifest is missing")
    raw = _read_bounded(manifest_path, limits.max_metadata_bytes)
    try:
        data = json.loads(raw, object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise MigrationPackageError("invalid_manifest", "Manifest is not valid JSON") from exc
    manifest = _parse_manifest(data)
    total_bytes = 0
    seen_paths: set[str] = set()
    seen_ids: set[str] = set()
    actual_counts: dict[str, int] = {}
    for record in manifest.records:
        if record.package_path in seen_paths or record.source_id in seen_ids:
            raise MigrationPackageError("invalid_manifest", "Manifest records are duplicated")
        seen_paths.add(record.package_path)
        seen_ids.add(record.source_id)
        expected_source_id = source_record_id(
            manifest.source_identifier, record.source_path, record.checksum_sha256
        )
        if record.source_id != expected_source_id:
            raise MigrationPackageError(
                "invalid_manifest", "Record source identity does not match its content"
            )
        path = _safe_join(root, record.package_path)
        if not path.is_file() or path.is_symlink():
            raise MigrationPackageError("invalid_record", "Package record is missing")
        content = _read_bounded(path, limits.max_file_bytes)
        total_bytes += len(content)
        _check_package_limits(len(seen_paths), total_bytes, limits)
        if len(content) != record.size_bytes:
            raise MigrationPackageError("checksum_mismatch", "Record size does not match")
        if sha256_bytes(content) != record.checksum_sha256:
            raise MigrationPackageError("checksum_mismatch", "Record checksum does not match")
        if record.record_type == "document":
            if _media_type(path) != record.media_type:
                raise MigrationPackageError("invalid_record", "Document media type is unsupported")
            _reject_secret_content(content)
        actual_counts[record.record_type] = actual_counts.get(record.record_type, 0) + 1
    expected_files = {MANIFEST_NAME, *seen_paths}
    if package_files != expected_files:
        raise MigrationPackageError(
            "invalid_manifest", "Package contains files not declared by the manifest"
        )
    if dict(manifest.counts) != actual_counts:
        raise MigrationPackageError("invalid_manifest", "Manifest record counts do not match")
    return LoadedMigrationPackage(root, manifest, sha256_bytes(_canonical_json(data)))


def read_package_record(
    package: LoadedMigrationPackage, record: MigrationRecord
) -> bytes:
    """Revalidate one file immediately before use to prevent package mutation races."""
    path = _safe_join(package.root, record.package_path)
    _require_safe_source_file(path, package.root)
    content = _read_bounded(path, record.size_bytes)
    if len(content) != record.size_bytes or sha256_bytes(content) != record.checksum_sha256:
        raise MigrationPackageError(
            "checksum_mismatch", "Record changed after package validation"
        )
    if record.record_type == "document":
        _reject_secret_content(content)
    return content


def _parse_manifest(data: Any) -> MigrationManifest:
    if not isinstance(data, dict):
        raise MigrationPackageError("invalid_manifest", "Manifest must be an object")
    allowed = {
        "schema_version",
        "source_version",
        "source_type",
        "source_identifier",
        "created_at",
        "migration_tool_version",
        "source_build_sha",
        "counts",
        "workspace_config",
        "omitted",
        "records",
    }
    if set(data) - allowed:
        raise MigrationPackageError("invalid_manifest", "Manifest has unknown fields")
    if data.get("schema_version") != MIGRATION_SCHEMA_VERSION:
        raise MigrationPackageError("unsupported_version", "Migration schema is unsupported")
    if data.get("source_version") != "2" or data.get("source_type") != "aira-v2-workspace":
        raise MigrationPackageError("unsupported_version", "Migration source is unsupported")
    try:
        created_at = datetime.fromisoformat(str(data["created_at"]))
    except (KeyError, ValueError) as exc:
        raise MigrationPackageError("invalid_manifest", "Manifest timestamp is invalid") from exc
    if created_at.tzinfo is None:
        raise MigrationPackageError("invalid_manifest", "Manifest timestamp requires a timezone")
    records_data = data.get("records")
    if not isinstance(records_data, list):
        raise MigrationPackageError("invalid_manifest", "Manifest records must be a list")
    records = tuple(_parse_record(item) for item in records_data)
    counts_data = data.get("counts")
    if not isinstance(counts_data, dict) or any(
        not isinstance(key, str) or isinstance(value, bool) or not isinstance(value, int)
        or value < 0
        for key, value in counts_data.items()
    ):
        raise MigrationPackageError("invalid_manifest", "Manifest counts are invalid")
    config_data = data.get("workspace_config", {})
    if not isinstance(config_data, dict) or set(config_data) - _CONFIG_ALLOWLIST:
        raise MigrationPackageError("invalid_manifest", "Workspace config is not allowlisted")
    _reject_secret_metadata(data)
    omitted_data = data.get("omitted", [])
    if not isinstance(omitted_data, list) or not all(
        isinstance(item, str) for item in omitted_data
    ):
        raise MigrationPackageError("invalid_manifest", "Manifest omissions are invalid")
    return MigrationManifest(
        schema_version=MIGRATION_SCHEMA_VERSION,
        source_version="2",
        source_type="aira-v2-workspace",
        source_identifier=_bounded_text(data.get("source_identifier"), "source identifier"),
        created_at=created_at,
        migration_tool_version=_bounded_text(
            data.get("migration_tool_version"), "migration tool version"
        ),
        source_build_sha=_source_build_sha(data.get("source_build_sha")),
        records=records,
        counts=tuple(sorted(counts_data.items())),
        workspace_config=tuple(sorted(config_data.items())),
        omitted=tuple(_bounded_text(item, "omitted item") for item in omitted_data),
    )


def _parse_record(data: Any) -> MigrationRecord:
    if not isinstance(data, dict) or set(data) != {
        "source_id",
        "record_type",
        "package_path",
        "source_path",
        "checksum_sha256",
        "size_bytes",
        "media_type",
        "category",
    }:
        raise MigrationPackageError("invalid_manifest", "Migration record shape is invalid")
    record_type = data["record_type"]
    if record_type not in {"document", "historical_only"}:
        raise MigrationPackageError("invalid_record", "Migration record type is unsupported")
    package_path = _safe_relative_path(data["package_path"])
    source_path = _safe_relative_path(data["source_path"])
    checksum = str(data["checksum_sha256"])
    if not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise MigrationPackageError("invalid_record", "Record checksum is invalid")
    size = data["size_bytes"]
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise MigrationPackageError("invalid_record", "Record size is invalid")
    category = data["category"]
    if record_type == "document" and category not in set(_DOCUMENT_DIRECTORIES.values()):
        raise MigrationPackageError("invalid_record", "Document category is invalid")
    if record_type != "document" and category is not None:
        raise MigrationPackageError("invalid_record", "Historical record category is invalid")
    if record_type == "document" and not _SAFE_FILENAME_RE.fullmatch(
        PurePosixPath(source_path).name
    ):
        raise MigrationPackageError("invalid_record", "Document filename is invalid")
    return MigrationRecord(
        source_id=_hex_id(data["source_id"]),
        record_type=record_type,
        package_path=package_path,
        source_path=source_path,
        checksum_sha256=checksum,
        size_bytes=size,
        media_type=_bounded_text(data["media_type"], "media type"),
        category=category,
    )


def _read_workspace_config(
    source: Path, limits: MigrationLimits
) -> tuple[dict[str, Any], tuple[str, ...]]:
    path = source / "config" / "operator_overrides.yaml"
    if not path.exists():
        return {}, ()
    _require_safe_source_file(path, source)
    raw = _read_bounded(path, limits.max_metadata_bytes)
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise MigrationPackageError("invalid_record", "Workspace config is invalid") from exc
    if not isinstance(data, dict):
        raise MigrationPackageError("invalid_record", "Workspace config must be an object")
    _reject_secret_metadata(data)
    selected = {key: data[key] for key in sorted(data) if key in _CONFIG_ALLOWLIST}
    omitted = tuple(f"workspace_config:{key}" for key in sorted(set(data) - _CONFIG_ALLOWLIST))
    return selected, omitted


def _validate_package_tree(root: Path, limits: MigrationLimits) -> set[str]:
    count = 0
    total = 0
    files: set[str] = set()
    for path in root.rglob("*"):
        source_stat = path.lstat()
        mode = source_stat.st_mode
        if stat.S_ISLNK(mode):
            raise MigrationPackageError("invalid_record", "Package symlinks are forbidden")
        if path.is_dir():
            continue
        if not stat.S_ISREG(mode):
            raise MigrationPackageError("invalid_record", "Package contains a special file")
        if source_stat.st_nlink > 1:
            raise MigrationPackageError("invalid_record", "Package hard links are forbidden")
        count += 1
        total += path.stat().st_size
        _check_package_limits(count, total, limits)
        files.add(path.relative_to(root).as_posix())
    return files


def _require_safe_source_file(path: Path, source: Path) -> None:
    source_stat = path.lstat()
    mode = source_stat.st_mode
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise MigrationPackageError("invalid_record", "V2 source contains an unsafe file")
    if source_stat.st_nlink > 1:
        raise MigrationPackageError("invalid_record", "V2 source hard links are forbidden")
    try:
        path.resolve(strict=True).relative_to(source)
    except ValueError as exc:
        raise MigrationPackageError("invalid_record", "V2 source file escapes source root") from exc


def _safe_join(root: Path, relative: str) -> Path:
    normalized = _safe_relative_path(relative)
    candidate = root.joinpath(*PurePosixPath(normalized).parts)
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise MigrationPackageError("invalid_record", "Package path escapes root") from exc
    return candidate


def _safe_relative_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise MigrationPackageError("invalid_record", "Package path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise MigrationPackageError("invalid_record", "Package path is unsafe")
    if len(value) > 1_024:
        raise MigrationPackageError("invalid_record", "Package path is too long")
    return path.as_posix()


def _media_type(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in _MEDIA_TYPES:
        return _MEDIA_TYPES[suffix]
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed if suffix in _MEDIA_TYPES else None


def _read_bounded(path: Path, maximum: int) -> bytes:
    if path.stat().st_size > maximum:
        raise MigrationPackageError("invalid_record", "Migration file exceeds size limit")
    return path.read_bytes()


def _check_package_limits(count: int, total: int, limits: MigrationLimits) -> None:
    if count > limits.max_files:
        raise MigrationPackageError("invalid_record", "Migration package has too many files")
    if total > limits.max_total_bytes:
        raise MigrationPackageError("invalid_record", "Migration package is too large")


def _reject_secret_metadata(value: Any, *, key: str = "") -> None:
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            if _SECRET_KEY_RE.search(str(child_key)):
                raise MigrationPackageError(
                    "invalid_record", "Migration metadata contains a secret-like field"
                )
            _reject_secret_metadata(child_value, key=str(child_key))
    elif isinstance(value, list):
        for child in value:
            _reject_secret_metadata(child, key=key)
    elif isinstance(value, str) and _SECRET_VALUE_RE.search(value):
        raise MigrationPackageError(
            "invalid_record", "Migration metadata contains secret-like content"
        )


def _reject_secret_content(content: bytes) -> None:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MigrationPackageError(
            "invalid_record", "Migration text document is not valid UTF-8"
        ) from exc
    if _SECRET_VALUE_RE.search(text) or _SECRET_ASSIGNMENT_RE.search(text):
        raise MigrationPackageError(
            "invalid_record", "Migration document contains secret-like content"
        )


def _record_counts(records: list[MigrationRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        counts[record.record_type] = counts.get(record.record_type, 0) + 1
    return dict(sorted(counts.items()))


def _record_json(record: MigrationRecord) -> dict[str, Any]:
    return {
        "source_id": record.source_id,
        "record_type": record.record_type,
        "package_path": record.package_path,
        "source_path": record.source_path,
        "checksum_sha256": record.checksum_sha256,
        "size_bytes": record.size_bytes,
        "media_type": record.media_type,
        "category": record.category,
    }


def _canonical_json(data: Any) -> bytes:
    return (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _bounded_text(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise MigrationPackageError("invalid_manifest", f"Manifest {label} is invalid")
    normalized = value.strip()
    if not normalized or len(normalized) > 255 or any(char in normalized for char in "\r\n"):
        raise MigrationPackageError("invalid_manifest", f"Manifest {label} is invalid")
    return normalized


def _optional_bounded_text(value: Any) -> str | None:
    return None if value is None else _bounded_text(value, "source build SHA")


def _source_build_sha(value: Any) -> str | None:
    normalized = _optional_bounded_text(value)
    if normalized is not None and not re.fullmatch(r"[0-9a-f]{40}", normalized):
        raise MigrationPackageError("invalid_manifest", "Source build SHA is invalid")
    return normalized


def _hex_id(value: Any) -> str:
    normalized = str(value)
    if not re.fullmatch(r"[0-9a-f]{64}", normalized):
        raise MigrationPackageError("invalid_record", "Source record identity is invalid")
    return normalized


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MigrationPackageError(
                "invalid_manifest", "Manifest contains a duplicate field"
            )
        result[key] = value
    return result
