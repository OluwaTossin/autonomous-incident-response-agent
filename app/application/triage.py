"""Reusable triage execution independent of delivery and persistence adapters."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4


class TriagePipeline(Protocol):
    """Run triage reasoning and return its result plus non-client metadata."""

    def __call__(
        self,
        incident: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]: ...


@dataclass(frozen=True)
class TriageExecution:
    """One completed triage execution and its adapter-facing metadata."""

    result: dict[str, Any]
    metadata: dict[str, Any]
    duration_ms: int

    @property
    def triage_id(self) -> str:
        return str(self.result["triage_id"])


def _new_triage_id() -> str:
    return str(uuid4())


def execute_triage(
    incident: dict[str, Any],
    *,
    pipeline: TriagePipeline,
    id_factory: Callable[[], str] = _new_triage_id,
    clock: Callable[[], float] = time.perf_counter,
) -> TriageExecution:
    """Run a triage pipeline without performing audit, metric, or HTTP side effects."""
    started_at = clock()
    result, metadata = pipeline(incident)
    duration_ms = int((clock() - started_at) * 1000)
    triage_id = id_factory()
    return TriageExecution(
        result={**result, "triage_id": triage_id},
        metadata=dict(metadata),
        duration_ms=duration_ms,
    )
