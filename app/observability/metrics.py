"""Provider-neutral bounded metrics with a CloudWatch EMF adapter."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

FORBIDDEN_DIMENSIONS = frozenset(
    {
        "organization_id",
        "workspace_id",
        "actor_id",
        "incident_id",
        "triage_run_id",
        "triage_id",
        "job_id",
        "dispatch_id",
        "integration_id",
        "action_proposal_id",
        "approval_id",
        "execution_intent_id",
        "alarm_name",
        "log_group",
    }
)
ALLOWED_DIMENSIONS = frozenset(
    {
        "Environment",
        "Service",
        "Operation",
        "Result",
        "JobType",
        "Collector",
        "Provider",
        "StatusClass",
        "AlarmState",
        "ProposalType",
        "Risk",
        "Connector",
    }
)
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_VALUE = re.compile(r"^[A-Za-z0-9_.:/-]{1,64}$")


class MetricDimensionsError(ValueError):
    pass


class MetricSink(Protocol):
    def counter(self, name: str, value: float = 1, **dimensions: str) -> None: ...
    def gauge(self, name: str, value: float, **dimensions: str) -> None: ...
    def histogram(
        self, name: str, value: float, *, unit: str = "Milliseconds", **dimensions: str
    ) -> None: ...


def validate_dimensions(dimensions: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for name, value in dimensions.items():
        if name.casefold() in FORBIDDEN_DIMENSIONS or name not in ALLOWED_DIMENSIONS:
            raise MetricDimensionsError(f"Metric dimension {name!r} is not allowlisted")
        rendered = str(value)
        if not _VALUE.fullmatch(rendered):
            raise MetricDimensionsError(f"Metric dimension {name!r} has an invalid value")
        normalized[name] = rendered
    return normalized


def _metric_name(name: str) -> str:
    if not _NAME.fullmatch(name):
        raise ValueError("Metric name must be a fixed lower-snake-case identifier")
    return name


class CloudWatchEmfMetricSink:
    def __init__(self, namespace: str, environment: str, service: str) -> None:
        if namespace != "AIRA/Hosted":
            raise ValueError("Hosted metric namespace must be AIRA/Hosted")
        self._namespace = namespace
        self._base = {"Environment": environment, "Service": service}

    def counter(self, name: str, value: float = 1, **dimensions: str) -> None:
        self._emit(name, value, "Count", dimensions)

    def gauge(self, name: str, value: float, **dimensions: str) -> None:
        self._emit(name, value, "None", dimensions)

    def histogram(
        self, name: str, value: float, *, unit: str = "Milliseconds", **dimensions: str
    ) -> None:
        self._emit(name, value, unit, dimensions)

    def _emit(
        self, name: str, value: float, unit: str, dimensions: dict[str, str]
    ) -> None:
        metric_name = _metric_name(name)
        complete = validate_dimensions({**self._base, **dimensions})
        base_names = ["Environment", "Service"]
        all_names = sorted(complete)
        dimension_sets = [all_names]
        if all_names != base_names:
            dimension_sets.append(base_names)
        payload: dict[str, object] = {
            "_aws": {
                "Timestamp": int(datetime.now(UTC).timestamp() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": self._namespace,
                        "Dimensions": dimension_sets,
                        "Metrics": [{"Name": metric_name, "Unit": unit}],
                    }
                ],
            },
            **complete,
            metric_name: value,
        }
        sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
        sys.stdout.flush()


@dataclass
class InMemoryMetricSink:
    records: list[tuple[str, float, str, dict[str, str]]] = field(default_factory=list)

    def counter(self, name: str, value: float = 1, **dimensions: str) -> None:
        self._record(name, value, "Count", dimensions)

    def gauge(self, name: str, value: float, **dimensions: str) -> None:
        self._record(name, value, "None", dimensions)

    def histogram(
        self, name: str, value: float, *, unit: str = "Milliseconds", **dimensions: str
    ) -> None:
        self._record(name, value, unit, dimensions)

    def _record(self, name: str, value: float, unit: str, dimensions: dict[str, str]) -> None:
        self.records.append((_metric_name(name), value, unit, validate_dimensions(dimensions)))


class LifecycleMetricObserver:
    def __init__(self, sink: MetricSink, service: str) -> None:
        self._sink = sink
        self._service = service

    def record(self, event: str, duration_ms: int, outcome: str) -> None:
        operation = _metric_name(event)
        dimensions = {"Operation": operation, "Result": outcome}
        self._sink.counter(f"{operation}_total", **dimensions)
        self._sink.histogram(
            f"{operation}_duration_ms", max(0, duration_ms), **dimensions
        )


class DispatchMetricObserver:
    def __init__(self, sink: MetricSink) -> None:
        self._sink = sink

    def record(self, event: str, outcome: str) -> None:
        operation = _metric_name(event)
        self._sink.counter(f"{operation}_total", Operation=operation, Result=outcome)


class ActionMetricObserver:
    def __init__(self, sink: MetricSink) -> None:
        self._sink = sink

    def record(self, event: str, proposal_type: str, risk: str, result: str) -> None:
        self._sink.counter(
            f"{_metric_name(event)}_total",
            ProposalType=proposal_type,
            Risk=risk,
            Result=result,
        )


class ApprovalMetricObserver:
    def __init__(self, sink: MetricSink) -> None:
        self._sink = sink

    def record(
        self,
        event: str,
        outcome: str,
        risk: str,
        proposal_type: str,
        duration_ms: int = 0,
    ) -> None:
        dimensions = {
            "ProposalType": proposal_type,
            "Risk": risk,
            "Result": outcome,
        }
        self._sink.counter(f"{_metric_name(event)}_total", **dimensions)
        if duration_ms:
            self._sink.histogram("approval_decision_latency_ms", duration_ms, **dimensions)


class ExecutionIntentMetricObserver:
    def __init__(self, sink: MetricSink) -> None:
        self._sink = sink

    def record(
        self, event: str, connector: str, operation: str, result: str, risk: str
    ) -> None:
        self._sink.counter(
            f"{_metric_name(event)}_total",
            Connector=connector,
            Operation=operation,
            Result=result,
            Risk=risk,
        )


class JobExecutionMetricObserver:
    def __init__(self, sink: MetricSink) -> None:
        self._sink = sink

    def record(
        self, event: str, duration_ms: int, outcome: str, job_type: str
    ) -> None:
        dimensions = {"JobType": job_type, "Result": outcome}
        operation = _metric_name(event)
        if operation == "job_queue_delay":
            self._sink.histogram("job_queue_delay_ms", max(0, duration_ms), **dimensions)
            return
        metric_name = (
            "job_execution_total" if operation.startswith("jobs_") else f"{operation}_total"
        )
        self._sink.counter(metric_name, **dimensions)
        if duration_ms:
            self._sink.histogram("job_duration_ms", max(0, duration_ms), **dimensions)


class ContextSnapshotMetricObserver:
    def __init__(self, sink: MetricSink) -> None:
        self._sink = sink

    def record_snapshot(
        self, *, item_count: int, truncated: bool, result: str, provider: str
    ) -> None:
        dimensions = {"Collector": "aggregate", "Provider": provider, "Result": result}
        self._sink.histogram(
            "context_items_collected", max(0, item_count), unit="Count", **dimensions
        )
        if truncated:
            self._sink.counter("context_truncated_total", **dimensions)


class OutboxBacklogMetricObserver:
    def __init__(self, sink: MetricSink) -> None:
        self._sink = sink

    def record_backlog(
        self, *, pending_count: int, oldest_age_seconds: float, claimed_count: int
    ) -> None:
        dimensions = {"Result": "snapshot"}
        self._sink.gauge("outbox_pending_count", max(0, pending_count), **dimensions)
        self._sink.gauge(
            "outbox_oldest_pending_age_seconds",
            max(0, oldest_age_seconds),
            **dimensions,
        )
        self._sink.gauge("outbox_claimed_count", max(0, claimed_count), **dimensions)


@dataclass(frozen=True, slots=True)
class HostedMetricObservers:
    lifecycle: LifecycleMetricObserver
    dispatch: DispatchMetricObserver
    actions: ActionMetricObserver
    approvals: ApprovalMetricObserver
    execution_intents: ExecutionIntentMetricObserver
    job_execution: JobExecutionMetricObserver
    context_snapshots: ContextSnapshotMetricObserver
    outbox_backlog: OutboxBacklogMetricObserver

    @classmethod
    def build(cls, sink: MetricSink, service: str) -> HostedMetricObservers:
        return cls(
            LifecycleMetricObserver(sink, service),
            DispatchMetricObserver(sink),
            ActionMetricObserver(sink),
            ApprovalMetricObserver(sink),
            ExecutionIntentMetricObserver(sink),
            JobExecutionMetricObserver(sink),
            ContextSnapshotMetricObserver(sink),
            OutboxBacklogMetricObserver(sink),
        )
