"""Hosted telemetry composition shared by API and background runtimes."""

from __future__ import annotations

from dataclasses import dataclass

from app.config.settings import Settings
from app.observability.metrics import (
    CloudWatchEmfMetricSink,
    HostedMetricObservers,
    MetricSink,
)
from app.observability.tracing import configure_tracing


@dataclass(frozen=True, slots=True)
class HostedTelemetry:
    service: str
    environment: str
    build_sha: str
    metrics: MetricSink
    observers: HostedMetricObservers

    @classmethod
    def from_settings(cls, settings: Settings, service: str) -> HostedTelemetry:
        sink = CloudWatchEmfMetricSink(
            settings.aira_metric_namespace,
            settings.aira_env,
            service,
        )
        configure_tracing(
            service=service,
            environment=settings.aira_env,
            build_sha=settings.aira_build_sha,
            endpoint=settings.aira_otel_exporter_endpoint,
            sample_ratio=settings.aira_trace_sample_ratio,
        )
        return cls(
            service,
            settings.aira_env,
            settings.aira_build_sha,
            sink,
            HostedMetricObservers.build(sink, service),
        )
