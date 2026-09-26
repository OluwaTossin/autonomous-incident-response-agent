from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2] / "infra" / "terraform" / "hosted"


def _text(name: str) -> str:
    return (ROOT / "modules" / "platform" / name).read_text(encoding="utf-8")


def test_hosted_tasks_and_database_are_not_public() -> None:
    runtime = _text("runtime.tf")
    data = _text("data.tf")
    assert runtime.count("assign_public_ip = false") >= 5
    assert re.search(r"publicly_accessible\s*=\s*false", data)
    assert 'cidr_ipv4         = "0.0.0.0/0"' not in _text("security.tf").split(
        'resource "aws_security_group" "database"'
    )[1]


def test_images_are_immutable_and_no_provider_mutation_permissions_exist() -> None:
    runtime = _text("runtime.tf")
    assert 'image_tag_mutability = "IMMUTABLE"' in runtime
    assert "@${var.api_image_digest}" in runtime
    assert "@${var.worker_image_digest}" in runtime
    assert "@${var.web_image_digest}" in runtime
    assert "var.enable_runtime_services ? var.api_desired_count : 0" in runtime
    assert "var.enable_runtime_services ? var.worker_desired_count : 0" in runtime
    assert "var.enable_runtime_services ? var.web_desired_count : 0" in runtime
    for forbidden in (
        "ec2:TerminateInstances",
        "autoscaling:SetDesiredCapacity",
        "lambda:UpdateFunctionCode",
        "ecs:UpdateService",
    ):
        assert forbidden not in runtime


def test_v2_terraform_tree_remains_separate() -> None:
    assert (ROOT.parent / "envs" / "dev" / "frontend_cdn.tf").is_file()
    assert "../../modules/platform" in (ROOT / "envs" / "dev" / "main.tf").read_text()


def test_hosted_observability_dependencies_do_not_enter_v2_image() -> None:
    repository = ROOT.parents[2]
    assert "--extra hosted" in (repository / "Dockerfile.hosted").read_text()
    assert "--extra hosted" not in (repository / "Dockerfile").read_text()


def test_hosted_observability_has_required_dashboards_and_alarms() -> None:
    dashboards = _text("observability_dashboards.tf")
    alarms = _text("observability_alarms.tf")
    monitoring = _text("monitoring.tf")
    runtime = _text("runtime.tf")
    assert dashboards.count('resource "aws_cloudwatch_dashboard"') == 4
    for resource in (
        'resource "aws_cloudwatch_metric_alarm" "target_unhealthy"',
        'resource "aws_cloudwatch_metric_alarm" "target_5xx"',
        'resource "aws_cloudwatch_metric_alarm" "queue_age"',
        'resource "aws_cloudwatch_metric_alarm" "worker_count"',
        'resource "aws_cloudwatch_metric_alarm" "database_storage"',
    ):
        assert resource in alarms
    assert 'resource "aws_cloudwatch_metric_alarm" "jobs_dlq"' in monitoring
    assert 'resource "aws_cloudwatch_metric_alarm" "alerts_dlq"' in monitoring
    assert "alarm_actions = var.alarm_action_arns" in alarms
    assert "retention_in_days = var.log_retention_days" in runtime


def test_observability_terraform_has_no_tenant_metric_dimensions() -> None:
    source = (_text("observability_dashboards.tf") + _text("observability_alarms.tf")).casefold()
    for forbidden in (
        "organization_id",
        "workspace_id",
        "incident_id",
        "triage_run_id",
        "job_id",
        "integration_id",
        "log_group",
    ):
        assert forbidden not in source
