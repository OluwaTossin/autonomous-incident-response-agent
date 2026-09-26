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
