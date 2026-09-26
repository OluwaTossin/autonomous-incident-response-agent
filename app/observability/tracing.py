"""Small OpenTelemetry composition with privacy-enforced span attributes."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

SAFE_TRACE_ATTRIBUTES = frozenset(
    {
        "service.name",
        "deployment.environment",
        "service.version",
        "http.request.method",
        "http.route",
        "http.response.status_code",
        "job.type",
        "job.result",
        "aws.collector",
        "aws.provider",
        "operation.name",
        "error.category",
    }
)


def configure_tracing(
    *,
    service: str,
    environment: str,
    build_sha: str,
    endpoint: str,
    sample_ratio: float,
) -> None:
    if not endpoint:
        return
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": service,
                "deployment.environment": environment,
                "service.version": build_sha,
            }
        ),
        sampler=ParentBased(TraceIdRatioBased(sample_ratio)),
    )
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)


@contextmanager
def span(name: str, **attributes: object) -> Iterator[trace.Span]:
    unsafe = sorted(set(attributes) - SAFE_TRACE_ATTRIBUTES)
    if unsafe:
        raise ValueError("Unsafe trace attributes: " + ", ".join(unsafe))
    tracer = trace.get_tracer("aira.hosted")
    with tracer.start_as_current_span(name) as current:
        for key, value in attributes.items():
            if value is not None:
                current.set_attribute(key, value)
        yield current
