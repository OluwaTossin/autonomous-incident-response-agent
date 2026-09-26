"""Pure V2-to-V3 cutover evidence validation; performs no infrastructure calls."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class CutoverExpectation:
    database_revision: str
    source_manifest_hash: str
    document_count: int
    document_bytes: int


@dataclass(frozen=True, slots=True)
class CutoverValidation:
    ready: bool
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]


def validate_cutover(
    migration_report: dict[str, Any],
    release_manifest: dict[str, Any],
    expectation: CutoverExpectation,
    *,
    v2_regression_green: bool,
    v3_regression_green: bool,
    security_gates_green: bool,
    knowledge_state: str,
    fallback_plan_acknowledged: bool,
) -> CutoverValidation:
    """Return deterministic readiness reasons without changing traffic or data."""
    reasons: list[str] = []
    warnings: list[str] = []
    if migration_report.get("mode") != "verify":
        reasons.append("migration_report_not_verification")
    if migration_report.get("manifest_hash") != expectation.source_manifest_hash:
        reasons.append("source_manifest_hash_mismatch")
    if migration_report.get("rejected", 0) or migration_report.get("failed", 0):
        reasons.append("migration_verification_failed")
    if migration_report.get("document_count_verified") != expectation.document_count:
        reasons.append("document_count_mismatch")
    if migration_report.get("document_bytes_verified") != expectation.document_bytes:
        reasons.append("document_bytes_mismatch")
    if release_manifest.get("schema_version") != 1:
        reasons.append("release_manifest_unsupported")
    git_sha = release_manifest.get("git_sha")
    if not isinstance(git_sha, str) or not _SHA_RE.fullmatch(git_sha):
        reasons.append("release_git_sha_invalid")
    if release_manifest.get("migration_revision") != expectation.database_revision:
        reasons.append("database_revision_mismatch")
    images = release_manifest.get("images")
    if not isinstance(images, dict) or set(images) != {"api", "worker", "web"}:
        reasons.append("release_images_invalid")
    else:
        for service in ("api", "worker", "web"):
            image = images.get(service)
            digest = image.get("digest") if isinstance(image, dict) else None
            if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
                reasons.append(f"release_{service}_digest_invalid")
    if not v2_regression_green:
        reasons.append("v2_regression_not_green")
    if not v3_regression_green:
        reasons.append("v3_regression_not_green")
    if not security_gates_green:
        reasons.append("security_gates_not_green")
    if knowledge_state != "active":
        reasons.append("knowledge_bundle_not_active")
    if not fallback_plan_acknowledged:
        reasons.append("fallback_plan_not_acknowledged")
    warnings.extend(
        (
            "users_must_reauthenticate_with_v3_identity",
            "fallback_requires_reconciliation_after_v3_only_writes",
            "this_validator_does_not_authorize_production_cutover",
        )
    )
    return CutoverValidation(not reasons, tuple(sorted(set(reasons))), tuple(warnings))
