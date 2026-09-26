from __future__ import annotations

import pytest

from scripts.readiness.capacity import ServicePool, evaluate_connection_budget, percentile
from scripts.readiness.egress_check import validate_endpoint
from scripts.readiness.load_harness import SYNTHETIC_MARKER, validate_target
from scripts.readiness.prerequisites import Requirement, check_requirements, prerequisites_ready


class Probe:
    def __init__(self, present: set[tuple[str, str]], current: set[str]) -> None:
        self.present = present
        self.current = current

    def exists(self, kind: str, identifier: str) -> bool:
        return (kind, identifier) in self.present

    def has_current_version(self, identifier: str) -> bool:
        return identifier in self.current


def test_connection_budget_reserves_database_headroom() -> None:
    pools = (
        ServicePool("api", 2, 5, 10),
        ServicePool("worker", 2, 5, 10),
        ServicePool("dispatcher", 1, 5, 10),
        ServicePool("alert-ingestion", 1, 5, 10),
        ServicePool("web", 2, 5, 0),
    )
    accepted = evaluate_connection_budget(pools, database_max_connections=200)
    rejected = evaluate_connection_budget(pools, database_max_connections=100)
    assert accepted.total == 100
    assert accepted.accepted and accepted.headroom == 50
    assert not rejected.accepted and rejected.headroom == -25


def test_prerequisite_probe_checks_presence_and_secret_version_without_values() -> None:
    requirements = (
        Requirement("ecs-service", "api"),
        Requirement("secret", "cursor-key", must_have_current_version=True),
    )
    ready = check_requirements(
        requirements,
        Probe({("ecs-service", "api"), ("secret", "cursor-key")}, {"cursor-key"}),
    )
    missing_version = check_requirements(
        requirements,
        Probe({("ecs-service", "api"), ("secret", "cursor-key")}, set()),
    )
    assert prerequisites_ready(ready)
    assert not prerequisites_ready(missing_version)


@pytest.mark.parametrize(
    "target",
    [
        "https://production.aira.example",
        "https://prod.aira.example",
        "https://unknown.example",
        "file:///etc/passwd",
    ],
)
def test_load_harness_rejects_unsafe_targets(target: str) -> None:
    with pytest.raises(ValueError):
        validate_target(target, {"staging.aira.example"})


def test_load_harness_accepts_only_localhost_or_allowlisted_staging() -> None:
    assert validate_target("http://127.0.0.1:8000", set())
    assert validate_target("https://staging.aira.example", {"staging.aira.example"})
    assert SYNTHETIC_MARKER == "AIRA_SYNTHETIC_DO_NOT_ESCALATE"
    assert percentile([1, 2, 3, 4, 100], 0.95) == 100


def test_egress_check_requires_exact_allowlisted_https_origin() -> None:
    assert validate_endpoint(
        "https://api.openai.example", {"api.openai.example"}
    ) == ("api.openai.example", 443)
    for value in (
        "http://api.openai.example",
        "https://user@api.openai.example",
        "https://api.openai.example/v1",
        "https://unknown.example",
    ):
        with pytest.raises(ValueError):
            validate_endpoint(value, {"api.openai.example"})
