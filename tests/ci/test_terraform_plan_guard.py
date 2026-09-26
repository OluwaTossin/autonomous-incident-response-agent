from __future__ import annotations

import pytest

from scripts.deploy.terraform_plan_guard import PlanError, inspect_plan


def plan(*changes: tuple[str, str, list[str]]) -> dict[str, object]:
    return {
        "resource_changes": [
            {"address": address, "type": resource_type, "change": {"actions": actions}}
            for address, resource_type, actions in changes
        ]
    }


def test_allows_non_destructive_runtime_rollout() -> None:
    destructive, critical = inspect_plan(
        plan(
            ("module.platform.aws_ecs_task_definition.api", "aws_ecs_task_definition", ["create"]),
            ("module.platform.aws_ecs_service.api", "aws_ecs_service", ["update"]),
        )
    )
    assert destructive == []
    assert critical == []


@pytest.mark.parametrize(
    "resource_type",
    [
        "aws_db_instance",
        "aws_s3_bucket",
        "aws_kms_key",
        "aws_cognito_user_pool",
        "aws_cognito_user_pool_client",
        "aws_sqs_queue",
    ],
)
def test_blocks_critical_destroy_or_replacement(resource_type: str) -> None:
    _, critical = inspect_plan(
        plan((f"module.platform.{resource_type}.critical", resource_type, ["delete", "create"]))
    )
    assert critical == [f"replace: module.platform.{resource_type}.critical"]


def test_reports_noncritical_destroy_for_human_review() -> None:
    destructive, critical = inspect_plan(
        plan(("module.platform.aws_cloudwatch_dashboard.old", "aws_cloudwatch_dashboard", ["delete"]))
    )
    assert destructive == ["destroy: module.platform.aws_cloudwatch_dashboard.old"]
    assert critical == []


def test_rejects_malformed_plan() -> None:
    with pytest.raises(PlanError):
        inspect_plan({})
