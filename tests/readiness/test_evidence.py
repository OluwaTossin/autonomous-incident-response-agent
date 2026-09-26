from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.readiness.evidence import (
    CODE_CHECKS,
    HARD_CHECKS,
    LIVE_CHECKS,
    REHEARSAL_CHECKS,
    Decision,
    EvidenceError,
    ReleaseIdentity,
    evaluate,
)

SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64
WEB_DIGEST = "sha256:" + "c" * 64


def release(*, environment: str = "production") -> ReleaseIdentity:
    return ReleaseIdentity(SHA, DIGEST, DIGEST, WEB_DIGEST, "9e4b7a2c6d10", environment)


def complete_evidence() -> dict:
    identity = release()
    names = CODE_CHECKS | REHEARSAL_CHECKS | LIVE_CHECKS | HARD_CHECKS
    release_data = {
        "git_sha": identity.git_sha,
        "api_digest": identity.api_digest,
        "worker_digest": identity.worker_digest,
        "web_digest": identity.web_digest,
        "migration_revision": identity.migration_revision,
        "environment": identity.environment,
    }
    return {
        "schema_version": 1,
        "created_at": "2026-09-26T12:00:00Z",
        "release": release_data,
        "checks": {
            name: {"status": "LIVE_VALIDATED", "evidence_refs": [f"evidence/{name}.json"]}
            for name in names
        },
        "security_findings": [],
        "conditions": [],
        "go_live_approval": {
            "approved": True,
            "approval_reference": "change/approved-123",
            "release": dict(release_data),
        },
    }


def test_complete_exact_release_evidence_is_go() -> None:
    result = evaluate(complete_evidence(), expected_release=release())
    assert result.decision is Decision.GO
    assert result.code_ready and result.rehearsal_ready
    assert result.live_validated and result.go_live_approved


@pytest.mark.parametrize(
    "check",
    [
        "backups_restore",
        "tenant_isolation",
        "migration_validation",
        "terraform_destructive_guard",
        "runtime_secrets",
        "rollback_rehearsal",
    ],
)
def test_hard_gate_failure_is_no_go(check: str) -> None:
    evidence = complete_evidence()
    evidence["checks"][check]["status"] = "FAILED"
    result = evaluate(evidence, expected_release=release())
    assert result.decision is Decision.NO_GO
    assert any(check in blocker for blocker in result.blockers)


def test_code_and_rehearsal_can_be_ready_while_live_and_approval_are_pending() -> None:
    evidence = complete_evidence()
    for name in LIVE_CHECKS:
        evidence["checks"][name]["status"] = (
            "LOCAL_VALIDATED" if name in REHEARSAL_CHECKS else "PLANNED"
        )
    evidence["go_live_approval"] = {"approved": False}
    result = evaluate(evidence, expected_release=release())
    assert result.code_ready and result.rehearsal_ready
    assert not result.live_validated and not result.go_live_approved
    assert result.decision is Decision.NO_GO


def test_stale_sha_digest_revision_or_environment_is_rejected() -> None:
    for field, value in (
        ("git_sha", "d" * 40),
        ("web_digest", "sha256:" + "d" * 64),
        ("migration_revision", "deadbeef"),
        ("environment", "staging"),
    ):
        evidence = complete_evidence()
        evidence["release"][field] = value
        with pytest.raises(EvidenceError, match="does not match"):
            evaluate(evidence, expected_release=release())


def test_unresolved_high_finding_is_no_go() -> None:
    evidence = complete_evidence()
    evidence["security_findings"] = [
        {"id": "SEC-9", "severity": "HIGH", "status": "accepted"}
    ]
    result = evaluate(evidence, expected_release=release())
    assert result.decision is Decision.NO_GO
    assert any("unresolved HIGH" in blocker for blocker in result.blockers)


def test_owned_non_blocking_risk_produces_conditional_go() -> None:
    evidence = complete_evidence()
    evidence["conditions"] = [{
        "id": "RISK-1",
        "severity": "MEDIUM",
        "owner": "platform-owner",
        "deadline": "2026-10-31",
        "mitigation": "Restrict source hosts",
        "monitoring": "Alert on denied requests",
        "rollback_trigger": "Unexpected outbound destination",
    }]
    result = evaluate(evidence, expected_release=release())
    assert result.decision is Decision.CONDITIONAL
    assert result.conditions == ("RISK-1",)


def test_approval_must_bind_to_exact_release() -> None:
    evidence = complete_evidence()
    evidence["go_live_approval"] = deepcopy(evidence["go_live_approval"])
    evidence["go_live_approval"]["release"]["git_sha"] = "d" * 40
    result = evaluate(evidence, expected_release=release())
    assert not result.go_live_approved
    assert result.decision is Decision.NO_GO
