"""Tests for the runtime-neutral triage boundary and self-hosted composition."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.application.triage import TriageExecution, execute_triage
from app.composition.self_hosted import SelfHostedTriage


def test_execute_triage_has_no_runtime_side_effects() -> None:
    incident = {"alert_title": "CPU high"}

    execution = execute_triage(
        incident,
        pipeline=lambda actual: (
            {"incident_summary": actual["alert_title"], "severity": "HIGH"},
            {"retrieval_hits": [{"source": "runbook.md"}]},
        ),
        id_factory=lambda: "triage-123",
        clock=iter([10.0, 10.125]).__next__,
    )

    assert execution == TriageExecution(
        result={
            "incident_summary": "CPU high",
            "severity": "HIGH",
            "triage_id": "triage-123",
        },
        metadata={"retrieval_hits": [{"source": "runbook.md"}]},
        duration_ms=125,
    )
    assert incident == {"alert_title": "CPU high"}


@dataclass
class _AuditSpy:
    calls: list[tuple[dict[str, Any], TriageExecution]] = field(default_factory=list)

    def record(self, incident: dict[str, Any], execution: TriageExecution) -> None:
        self.calls.append((incident, execution))


@dataclass
class _MetricsSpy:
    calls: list[TriageExecution] = field(default_factory=list)

    def record(self, execution: TriageExecution) -> None:
        self.calls.append(execution)


def test_self_hosted_composition_runs_pipeline_then_runtime_adapters() -> None:
    audit = _AuditSpy()
    metrics = _MetricsSpy()
    app = SelfHostedTriage(
        pipeline=lambda incident: (
            {"incident_summary": incident["alert_title"], "severity": "LOW"},
            {"rag_context": "context"},
        ),
        audit_sink=audit,
        metrics_sink=metrics,
    )
    incident = {"alert_title": "Disk warning"}

    result = app.run(incident)

    assert result["incident_summary"] == "Disk warning"
    assert len(result["triage_id"]) == 36
    assert audit.calls == [(incident, metrics.calls[0])]
    assert metrics.calls[0].result == result
    assert metrics.calls[0].metadata == {"rag_context": "context"}
