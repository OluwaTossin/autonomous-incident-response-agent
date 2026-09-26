"""Pure migration cutover readiness validation tests."""

from app.migration.cutover import CutoverExpectation, validate_cutover


def _release():
    return {
        "schema_version": 1,
        "git_sha": "a" * 40,
        "migration_revision": "9e4b7a2c6d10",
        "images": {
            "api": {"digest": f"sha256:{'1' * 64}"},
            "worker": {"digest": f"sha256:{'1' * 64}"},
            "web": {"digest": f"sha256:{'2' * 64}"},
        },
    }


def test_cutover_validator_accepts_complete_matching_evidence() -> None:
    result = validate_cutover(
        {
            "mode": "verify",
            "manifest_hash": "b" * 64,
            "rejected": 0,
            "failed": 0,
            "document_count_verified": 2,
            "document_bytes_verified": 120,
        },
        _release(),
        CutoverExpectation("9e4b7a2c6d10", "b" * 64, 2, 120),
        v2_regression_green=True,
        v3_regression_green=True,
        security_gates_green=True,
        knowledge_state="active",
        fallback_plan_acknowledged=True,
    )
    assert result.ready
    assert result.reasons == ()
    assert "this_validator_does_not_authorize_production_cutover" in result.warnings


def test_cutover_validator_fails_closed_with_stable_reasons() -> None:
    release = _release()
    release["migration_revision"] = "old"
    result = validate_cutover(
        {"mode": "import", "manifest_hash": "wrong", "rejected": 1},
        release,
        CutoverExpectation("9e4b7a2c6d10", "b" * 64, 2, 120),
        v2_regression_green=False,
        v3_regression_green=False,
        security_gates_green=False,
        knowledge_state="ready",
        fallback_plan_acknowledged=False,
    )
    assert not result.ready
    assert "migration_report_not_verification" in result.reasons
    assert "database_revision_mismatch" in result.reasons
    assert "knowledge_bundle_not_active" in result.reasons
    assert "fallback_plan_not_acknowledged" in result.reasons
