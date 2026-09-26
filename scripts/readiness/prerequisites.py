"""Non-destructive prerequisite inventory using an injectable metadata probe."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Requirement:
    kind: str
    identifier: str
    must_have_current_version: bool = False


@dataclass(frozen=True, slots=True)
class ProbeResult:
    requirement: Requirement
    present: bool
    current_version: bool | None


class MetadataProbe(Protocol):
    def exists(self, kind: str, identifier: str) -> bool: ...
    def has_current_version(self, identifier: str) -> bool: ...


def check_requirements(requirements: tuple[Requirement, ...], probe: MetadataProbe) -> tuple[ProbeResult, ...]:
    results: list[ProbeResult] = []
    for requirement in requirements:
        present = probe.exists(requirement.kind, requirement.identifier)
        current = probe.has_current_version(requirement.identifier) if present and requirement.must_have_current_version else None
        results.append(ProbeResult(requirement, present, current))
    return tuple(results)


def prerequisites_ready(results: tuple[ProbeResult, ...]) -> bool:
    return all(result.present and result.current_version is not False for result in results)
