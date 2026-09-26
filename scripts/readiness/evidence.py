"""Fail-closed release-bound readiness evidence and go/no-go evaluation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{4,64}$")


class EvidenceError(ValueError):
    """Readiness evidence is malformed, stale, or incomplete."""


class EvidenceState(StrEnum):
    PLANNED = "PLANNED"
    LOCAL_VALIDATED = "LOCAL_VALIDATED"
    CI_VALIDATED = "CI_VALIDATED"
    LIVE_VALIDATED = "LIVE_VALIDATED"
    FAILED = "FAILED"


class Decision(StrEnum):
    GO = "GO"
    NO_GO = "NO_GO"
    CONDITIONAL = "CONDITIONAL"


STATE_RANK = {
    EvidenceState.PLANNED: 0,
    EvidenceState.LOCAL_VALIDATED: 1,
    EvidenceState.CI_VALIDATED: 2,
    EvidenceState.LIVE_VALIDATED: 3,
    EvidenceState.FAILED: -1,
}
CODE_CHECKS = frozenset({
    "evidence_schema", "security_release", "tenant_isolation",
    "migration_validation", "rollback_procedure", "restore_procedure",
    "failure_scenarios", "capacity_model", "v2_compatibility",
    "v4_execution_absent",
})
REHEARSAL_CHECKS = frozenset({
    "staging_procedure", "rollback_procedure", "restore_procedure",
    "migration_rehearsal", "load_harness", "incident_tabletop",
})
LIVE_CHECKS = frozenset({
    "infrastructure", "identity", "database", "storage", "queues",
    "observability", "migration_rehearsal", "rollback_rehearsal", "capacity",
    "provider_egress", "smoke_tests", "backups_restore", "alert_ingestion",
})
HARD_CHECKS = frozenset({
    "security_release", "tenant_isolation", "migration_validation",
    "rollback_rehearsal", "backups_restore", "runtime_secrets",
    "production_oidc_trust", "terraform_destructive_guard", "ecs_health",
    "api_readiness", "dlq_empty", "alert_ingestion", "cognito_login",
    "release_binding", "required_alarms", "data_integrity",
})


@dataclass(frozen=True, slots=True)
class ReleaseIdentity:
    git_sha: str
    api_digest: str
    worker_digest: str
    web_digest: str
    migration_revision: str
    environment: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ReleaseIdentity:
        try:
            identity = cls(**{field: value[field] for field in cls.__annotations__})
        except (KeyError, TypeError) as exc:
            raise EvidenceError("release identity is incomplete") from exc
        identity.validate()
        return identity

    def validate(self) -> None:
        if not SHA_RE.fullmatch(self.git_sha):
            raise EvidenceError("release git_sha must be 40 lowercase hex characters")
        for name, digest in (("api_digest", self.api_digest), ("worker_digest", self.worker_digest), ("web_digest", self.web_digest)):
            if not DIGEST_RE.fullmatch(digest):
                raise EvidenceError(f"{name} must be an immutable sha256 digest")
        if self.api_digest != self.worker_digest:
            raise EvidenceError("API and worker must use the same built image digest")
        if not REVISION_RE.fullmatch(self.migration_revision):
            raise EvidenceError("migration_revision is invalid")
        if self.environment not in {"staging", "production"}:
            raise EvidenceError("environment must be staging or production")


@dataclass(frozen=True, slots=True)
class Evaluation:
    decision: Decision
    code_ready: bool
    rehearsal_ready: bool
    live_validated: bool
    go_live_approved: bool
    blockers: tuple[str, ...]
    conditions: tuple[str, ...]


def load_evidence(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"unable to read readiness evidence: {exc}") from exc
    if not isinstance(value, dict):
        raise EvidenceError("readiness evidence must be an object")
    return value


def evaluate(evidence: dict[str, Any], *, expected_release: ReleaseIdentity) -> Evaluation:
    if evidence.get("schema_version") != 1:
        raise EvidenceError("schema_version must be 1")
    release = ReleaseIdentity.from_dict(_object(evidence, "release"))
    if release != expected_release:
        raise EvidenceError("evidence release identity does not match the candidate release")
    checks = _object(evidence, "checks")
    parsed = {name: _check_state(name, value) for name, value in checks.items()}
    required_names = CODE_CHECKS | REHEARSAL_CHECKS | LIVE_CHECKS | HARD_CHECKS
    blockers = [f"missing check: {name}" for name in sorted(required_names - parsed.keys())]
    for name in sorted(HARD_CHECKS & parsed.keys()):
        required = EvidenceState.LIVE_VALIDATED if name in LIVE_CHECKS else EvidenceState.CI_VALIDATED
        if STATE_RANK[parsed[name]] < STATE_RANK[required]:
            blockers.append(f"hard check not satisfied: {name}={parsed[name].value}")
    findings = evidence.get("security_findings")
    if not isinstance(findings, list):
        blockers.append("security_findings must be present")
    else:
        for finding in findings:
            if not isinstance(finding, dict):
                blockers.append("malformed security finding")
            elif finding.get("severity") in {"CRITICAL", "HIGH"} and finding.get("status") != "resolved":
                blockers.append(f"unresolved {finding.get('severity')} security finding: {finding.get('id', 'unknown')}")
    conditions = _conditions(evidence.get("conditions"), blockers)
    code_ready = _at_least(parsed, CODE_CHECKS, EvidenceState.CI_VALIDATED)
    rehearsal_ready = code_ready and _at_least(parsed, REHEARSAL_CHECKS, EvidenceState.LOCAL_VALIDATED)
    live_validated = _at_least(parsed, LIVE_CHECKS, EvidenceState.LIVE_VALIDATED)
    approval = evidence.get("go_live_approval")
    go_live_approved = bool(
        isinstance(approval, dict) and approval.get("approved") is True
        and isinstance(approval.get("approval_reference"), str)
        and approval["approval_reference"].strip()
        and approval.get("release") == _release_dict(release)
    )
    if not live_validated:
        blockers.append("live validation is incomplete")
    if not go_live_approved:
        blockers.append("explicit release-bound go-live approval is missing")
    blockers = list(dict.fromkeys(blockers))
    decision = Decision.NO_GO if blockers else (Decision.CONDITIONAL if conditions else Decision.GO)
    return Evaluation(decision, code_ready, rehearsal_ready, live_validated, go_live_approved, tuple(blockers), conditions)


def _object(value: dict[str, Any], field: str) -> dict[str, Any]:
    item = value.get(field)
    if not isinstance(item, dict):
        raise EvidenceError(f"{field} must be an object")
    return item


def _check_state(name: str, value: Any) -> EvidenceState:
    if not isinstance(value, dict) or not isinstance(value.get("evidence_refs"), list):
        raise EvidenceError(f"check {name} must include evidence_refs")
    try:
        return EvidenceState(value.get("status"))
    except ValueError as exc:
        raise EvidenceError(f"check {name} has an invalid status") from exc


def _at_least(checks: dict[str, EvidenceState], names: frozenset[str], state: EvidenceState) -> bool:
    return all(name in checks and STATE_RANK[checks[name]] >= STATE_RANK[state] for name in names)


def _conditions(value: Any, blockers: list[str]) -> tuple[str, ...]:
    if not isinstance(value, list):
        blockers.append("conditions must be present")
        return ()
    required = {"id", "severity", "owner", "deadline", "mitigation", "monitoring", "rollback_trigger"}
    validated: list[str] = []
    for item in value:
        if not isinstance(item, dict) or not required.issubset(item):
            blockers.append("conditional risk is missing required ownership fields")
        elif item["severity"] not in {"LOW", "MEDIUM"}:
            blockers.append(f"conditional risk {item.get('id')} has blocking severity")
        elif not all(isinstance(item[key], str) and item[key].strip() for key in required):
            blockers.append(f"conditional risk {item.get('id')} has empty ownership fields")
        else:
            validated.append(item["id"])
    return tuple(validated)


def _release_dict(release: ReleaseIdentity) -> dict[str, str]:
    return {field: getattr(release, field) for field in release.__annotations__}
