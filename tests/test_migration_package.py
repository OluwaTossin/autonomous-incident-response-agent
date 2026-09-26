"""Untrusted V2 migration package export and validation tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.migration.package import (
    MANIFEST_NAME,
    MigrationLimits,
    MigrationPackageError,
    export_v2_workspace,
    load_migration_package,
    sha256_bytes,
)

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


def _workspace(root: Path) -> Path:
    workspace = root / "v2-workspace"
    (workspace / "data" / "runbooks").mkdir(parents=True)
    (workspace / "data" / "logs").mkdir(parents=True)
    (workspace / "index").mkdir()
    (workspace / "config").mkdir()
    (workspace / "data" / "runbooks" / "checkout.md").write_text(
        "# Checkout failure\nRestart the deployment.\n", encoding="utf-8"
    )
    (workspace / "data" / "logs" / "triage_outputs.jsonl").write_text(
        '{"triage_id":"legacy-1"}\n', encoding="utf-8"
    )
    (workspace / "index" / "index.faiss").write_bytes(b"legacy-index")
    (workspace / "index" / "chunks.jsonl").write_text("{}\n", encoding="utf-8")
    (workspace / "config" / "operator_overrides.yaml").write_text(
        "rag_top_k: 6\nllm_model: legacy-model\n", encoding="utf-8"
    )
    return workspace


def test_export_is_read_only_versioned_and_separates_history(tmp_path: Path) -> None:
    source = _workspace(tmp_path)
    before = {
        path.relative_to(source).as_posix(): sha256_bytes(path.read_bytes())
        for path in source.rglob("*")
        if path.is_file()
    }

    package = export_v2_workspace(
        source,
        tmp_path / "package",
        source_identifier="customer-a/default",
        source_build_sha="a" * 40,
        created_at=NOW,
    )

    after = {
        path.relative_to(source).as_posix(): sha256_bytes(path.read_bytes())
        for path in source.rglob("*")
        if path.is_file()
    }
    assert before == after
    assert package.manifest.schema_version == 1
    assert len(package.documents) == 1
    assert package.documents[0].category == "runbook"
    assert dict(package.manifest.counts) == {"document": 1, "historical_only": 1}
    assert dict(package.manifest.workspace_config) == {"rag_top_k": 6}
    assert "workspace_config:llm_model" in package.manifest.omitted
    assert "local_faiss_index:rebuild_required" in package.manifest.omitted
    assert not (package.root / "knowledge" / "index.faiss").exists()


def test_manifest_and_content_are_deterministic_except_creation_time(
    tmp_path: Path,
) -> None:
    source = _workspace(tmp_path)
    first = export_v2_workspace(source, tmp_path / "one", created_at=NOW)
    second = export_v2_workspace(source, tmp_path / "two", created_at=NOW)
    assert first.manifest_hash == second.manifest_hash
    assert first.manifest.records == second.manifest.records


def test_corrupt_checksum_is_rejected(tmp_path: Path) -> None:
    package = export_v2_workspace(_workspace(tmp_path), tmp_path / "package")
    target = package.root / package.documents[0].package_path
    target.write_text("changed", encoding="utf-8")
    with pytest.raises(MigrationPackageError) as exc:
        load_migration_package(package.root)
    assert exc.value.category == "checksum_mismatch"


def test_unsupported_schema_is_rejected(tmp_path: Path) -> None:
    package = export_v2_workspace(_workspace(tmp_path), tmp_path / "package")
    manifest_path = package.root / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = 999
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(MigrationPackageError) as exc:
        load_migration_package(package.root)
    assert exc.value.category == "unsupported_version"


def test_path_traversal_and_symlink_are_rejected(tmp_path: Path) -> None:
    package = export_v2_workspace(_workspace(tmp_path), tmp_path / "package")
    manifest_path = package.root / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["records"][0]["package_path"] = "../outside.md"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(MigrationPackageError, match="unsafe"):
        load_migration_package(package.root)

    other = export_v2_workspace(_workspace(tmp_path / "other"), tmp_path / "other-package")
    (other.root / "linked").symlink_to(other.root / MANIFEST_NAME)
    with pytest.raises(MigrationPackageError, match="symlinks"):
        load_migration_package(other.root)


def test_oversized_package_is_rejected(tmp_path: Path) -> None:
    source = _workspace(tmp_path)
    with pytest.raises(MigrationPackageError, match="size limit"):
        export_v2_workspace(
            source,
            tmp_path / "package",
            limits=MigrationLimits(max_file_bytes=8),
        )


def test_secret_like_config_is_rejected_without_exporting_value(tmp_path: Path) -> None:
    source = _workspace(tmp_path)
    (source / "config" / "operator_overrides.yaml").write_text(
        "api_key: super-secret-value\n", encoding="utf-8"
    )
    with pytest.raises(MigrationPackageError) as exc:
        export_v2_workspace(source, tmp_path / "package")
    assert exc.value.category == "invalid_record"
    assert "super-secret-value" not in str(exc.value)


def test_secret_like_document_content_is_rejected(tmp_path: Path) -> None:
    source = _workspace(tmp_path)
    (source / "data" / "runbooks" / "checkout.md").write_text(
        "OPENAI_API_KEY=sk-this-is-not-exportable\n", encoding="utf-8"
    )
    with pytest.raises(MigrationPackageError, match="secret-like content"):
        export_v2_workspace(source, tmp_path / "package")


def test_duplicate_manifest_fields_are_rejected(tmp_path: Path) -> None:
    package = export_v2_workspace(_workspace(tmp_path), tmp_path / "package")
    manifest_path = package.root / MANIFEST_NAME
    raw = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text(
        raw.replace('{"counts":', '{"schema_version":1,"counts":', 1),
        encoding="utf-8",
    )
    with pytest.raises(MigrationPackageError, match="duplicate field"):
        load_migration_package(package.root)


def test_source_symlink_is_rejected(tmp_path: Path) -> None:
    source = _workspace(tmp_path)
    target = source / "outside.md"
    target.write_text("outside", encoding="utf-8")
    (source / "data" / "runbooks" / "linked.md").symlink_to(target)
    with pytest.raises(MigrationPackageError, match="unsafe file"):
        export_v2_workspace(source, tmp_path / "package")
