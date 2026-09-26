from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
HOSTED = ROOT / "infra" / "terraform" / "hosted" / "modules" / "platform"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_each_hosted_process_has_a_bounded_execution_and_task_role() -> None:
    runtime = _text(HOSTED / "runtime.tf")
    for process in (
        "api",
        "worker",
        "dispatcher",
        "web",
        "migration",
        "alert-ingestion",
    ):
        assert f'aws_iam_role.execution["{process}"].arn' in runtime
    assert "task_role_arn            = aws_iam_role.dispatcher.arn" in runtime
    assert "task_role_arn            = aws_iam_role.alert_ingestion.arn" in runtime
    assert "task_role_arn            = aws_iam_role.migration.arn" in runtime
    assert runtime.count('capabilities = { drop = ["ALL"] }') == 6


def test_runtime_roles_cannot_read_the_database_master_secret() -> None:
    runtime = _text(HOSTED / "runtime.tf")
    secrets_map = runtime.split("execution_secret_arns = {", 1)[1].split("}", 1)[0]
    assert secrets_map.count("master_user_secret") == 1
    assert "migration" in secrets_map


def test_storage_and_database_have_security_baselines() -> None:
    data = _text(HOSTED / "data.tf")
    assert 'object_ownership = "BucketOwnerEnforced"' in data
    assert 'name  = "rds.force_ssl"' in data
    assert re.search(r"publicly_accessible\s*=\s*false", data)
    assert re.search(r"storage_encrypted\s*=\s*true", data)


def test_supply_chain_inputs_are_immutable() -> None:
    for dockerfile in (
        ROOT / "Dockerfile",
        ROOT / "Dockerfile.hosted",
        ROOT / "frontend" / "Dockerfile",
        ROOT / "web" / "Dockerfile",
    ):
        content = _text(dockerfile)
        assert ":latest" not in content
        for line in content.splitlines():
            if line.startswith("FROM ") or line.startswith("COPY --from="):
                image = line.split()[1].removeprefix("--from=")
                if "/" in image or ":" in image:
                    assert "@sha256:" in image

    for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
        for match in re.findall(r"uses:\s+([^\s#]+)", _text(workflow)):
            reference = match.rsplit("@", 1)[-1]
            assert re.fullmatch(r"[0-9a-f]{40}", reference)


def test_iam_wildcards_are_limited_to_reviewed_aws_exceptions() -> None:
    matches: list[tuple[str, int]] = []
    for path in sorted(HOSTED.glob("*.tf")):
        for line_number, line in enumerate(_text(path).splitlines(), start=1):
            if re.search(r'(actions|resources)\s*=\s*\["\*"\]', line):
                matches.append((path.name, line_number))
    assert matches == [("data.tf", 5), ("data.tf", 20), ("runtime.tf", 91)]
