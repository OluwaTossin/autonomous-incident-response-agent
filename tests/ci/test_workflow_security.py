from __future__ import annotations

from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def _text(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_workflows_are_valid_yaml_and_actions_are_commit_pinned() -> None:
    for workflow in WORKFLOWS.glob("*.yml"):
        assert isinstance(yaml.load(workflow.read_text(), Loader=yaml.BaseLoader), dict)
        for action in re.findall(r"uses:\s+([^\s#]+)", workflow.read_text()):
            if action.startswith("./"):
                continue
            assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", action), (workflow, action)


def test_pr_ci_has_no_cloud_credentials_or_deployment() -> None:
    ci = _text("ci.yml")
    assert "id-token: write" not in ci
    assert "configure-aws-credentials" not in ci
    assert "terraform apply" not in ci
    assert "services:\n      postgres:" in ci
    assert "tests/postgres" in ci
    assert "npm ci" in ci
    assert ci.count("--audit-level=high") == 2
    assert "uv sync --frozen" in ci


def test_release_builds_once_and_never_publishes_latest() -> None:
    release = _text("release-build.yml")
    assert release.count("-f Dockerfile.hosted") == 1
    assert release.count("-f web/Dockerfile") == 1
    assert 'docker tag "aira-hosted:$GITHUB_SHA" "$API_REPOSITORY:$GITHUB_SHA"' in release
    assert 'docker tag "aira-hosted:$GITHUB_SHA" "$WORKER_REPOSITORY:$GITHUB_SHA"' in release
    assert ":latest" not in release
    assert "release_manifest.py create" in release


def test_production_is_manual_manifest_promotion_with_environment_approval() -> None:
    production = _text("deploy-production.yml")
    assert "workflow_dispatch:" in production
    assert "development_run_id:" in production
    assert "environment: production\n" in production
    assert "docker build" not in production
    assert "Promote exact development digests without rebuilding" in production
    assert "terraform_plan_guard.py" in production
    assert production.index("run_migration_task.sh production") < production.index(
        "TF_VAR_enable_runtime_services: \"true\""
    )


def test_deployments_fail_closed_before_runtime_activation() -> None:
    for name, environment in (
        ("deploy-dev.yml", "development"),
        ("deploy-production.yml", "production"),
    ):
        workflow = _text(name)
        migration = workflow.index(f"run_migration_task.sh {environment}")
        activation = workflow.index('TF_VAR_enable_runtime_services: "true"')
        assert migration < activation
        assert workflow.index("check_runtime_secrets.sh") < migration
        assert workflow.index("terraform_plan_guard.py") < workflow.index(
            "terraform -chdir=\"$TF_DIR\" apply"
        )


def test_no_long_lived_aws_keys_or_arbitrary_command_inputs() -> None:
    combined = "\n".join(path.read_text() for path in WORKFLOWS.glob("*.yml"))
    assert "AWS_ACCESS_KEY_ID" not in combined
    assert "AWS_SECRET_ACCESS_KEY" not in combined
    assert "eval " not in combined
    assert "command:" not in _text("deploy-production.yml")
    assert "terraform_path:" not in combined


def test_rollback_uses_previous_manifest_without_database_downgrade() -> None:
    rollback = _text("rollback-hosted.yml")
    assert "confirm_schema_compatible" in rollback
    assert "environment: ${{ inputs.environment }}" in rollback
    assert "docker build" not in rollback
    assert "alembic downgrade" not in rollback
    assert "terraform_plan_guard.py" in rollback
