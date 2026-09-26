import json
import logging
from io import StringIO
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.composition.hosted_api import build_hosted_api
from app.observability.context import correlation_id, log_context
from app.observability.logging import JsonLogFormatter, log_event
from app.observability.http import install_http_observability
from app.observability.metrics import (
    CloudWatchEmfMetricSink,
    HostedMetricObservers,
    InMemoryMetricSink,
    MetricDimensionsError,
)
from app.observability.slo import (
    api_request_is_eligible,
    burn_rate,
    error_budget_seconds,
)
from app.observability.telemetry import HostedTelemetry
from app.observability.tracing import span


def _telemetry() -> tuple[HostedTelemetry, InMemoryMetricSink]:
    sink = InMemoryMetricSink()
    return HostedTelemetry("api", "test", "abc123", sink, HostedMetricObservers.build(sink, "api")), sink


def test_correlation_ids_are_bounded_uuids() -> None:
    supplied = str(uuid4())
    assert correlation_id(supplied.upper()) == supplied
    assert UUID(correlation_id("not-a-uuid"))
    assert UUID(correlation_id("x" * 65))


def test_api_returns_and_measures_validated_correlation_id() -> None:
    telemetry, sink = _telemetry()
    client = TestClient(build_hosted_api(object(), lambda: None, telemetry=telemetry))
    supplied = str(uuid4())

    response = client.get("/healthz", headers={"x-correlation-id": supplied})
    replaced = client.get("/healthz", headers={"x-correlation-id": "unsafe/value"})

    assert response.headers["x-correlation-id"] == supplied
    assert UUID(replaced.headers["x-correlation-id"])
    assert any(name == "request_count" for name, *_ in sink.records)
    dimensions = [dimensions for _, _, _, dimensions in sink.records]
    assert all("correlation_id" not in item for item in dimensions)
    assert any(item["Operation"] == "healthz" for item in dimensions)


def test_unhandled_api_error_returns_correlation_without_exception_detail() -> None:
    telemetry, sink = _telemetry()
    application = FastAPI()
    install_http_observability(application, telemetry)

    @application.get("/explode", name="explode")
    def explode() -> None:
        raise RuntimeError("sensitive dependency detail")

    response = TestClient(application).get("/explode")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert UUID(response.headers["x-correlation-id"])
    assert any(name == "server_error_count" for name, *_ in sink.records)


def test_emitted_json_log_redacts_representative_secrets() -> None:
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter(service="worker", environment="test", build_sha="abc123"))
    logger = logging.getLogger("test.hosted.logging")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    key = "AKIA" + "A" * 16
    private_key = "-----BEGIN PRIVATE KEY-----secret-----END PRIVATE KEY-----"

    with log_context(correlation_id=str(uuid4()), job_id=str(uuid4())):
        log_event(
            logger,
            logging.INFO,
            "job.test",
            "Bearer secret-token",
            cookie="session=secret",
            database_url="postgresql://user:password@example/db",
            client_secret="provider-secret",
            aws_key=key,
            material=private_key,
            link="https://bucket.s3.example/item?X-Amz-Signature=signature-secret",
        )

    record = json.loads(stream.getvalue())
    rendered = json.dumps(record)
    assert record["event"] == "job.test"
    assert record["cookie"] == "[REDACTED]"
    assert "secret-token" not in rendered
    assert "password@example" not in rendered
    assert "provider-secret" not in rendered
    assert "signature-secret" not in rendered
    assert key not in rendered
    assert "BEGIN PRIVATE KEY" not in rendered
    assert record["correlation_id"]
    assert record["job_id"]


@pytest.mark.parametrize(
    "name",
    [
        "organization_id",
        "workspace_id",
        "incident_id",
        "triage_run_id",
        "job_id",
        "integration_id",
        "action_proposal_id",
        "approval_id",
        "execution_intent_id",
        "alarm_name",
        "log_group",
    ],
)
def test_metric_dimensions_reject_high_cardinality_identifiers(name: str) -> None:
    sink = InMemoryMetricSink()
    with pytest.raises(MetricDimensionsError):
        sink.counter("request_count", **{name: "identifier"})


def test_emf_has_bounded_dimensions_and_aggregate_rollup(capsys) -> None:
    sink = CloudWatchEmfMetricSink("AIRA/Hosted", "prod", "api")
    sink.histogram(
        "request_duration_ms",
        25,
        Operation="healthz",
        Result="succeeded",
        StatusClass="2xx",
    )
    payload = json.loads(capsys.readouterr().out)
    metadata = payload["_aws"]["CloudWatchMetrics"][0]
    assert metadata["Namespace"] == "AIRA/Hosted"
    assert ["Environment", "Service"] in metadata["Dimensions"]
    assert payload["Service"] == "api"
    assert not any(key.endswith("_id") for key in payload)


def test_job_execution_metrics_use_bounded_job_type_and_result() -> None:
    _, sink = _telemetry()
    observer = HostedMetricObservers.build(sink, "worker").job_execution
    observer.record("job_queue_delay", 1250, "loaded", "triage")
    observer.record("jobs_succeeded", 4500, "succeeded", "triage")

    assert sink.records == [
        (
            "job_queue_delay_ms",
            1250,
            "Milliseconds",
            {"JobType": "triage", "Result": "loaded"},
        ),
        (
            "job_execution_total",
            1,
            "Count",
            {"JobType": "triage", "Result": "succeeded"},
        ),
        (
            "job_duration_ms",
            4500,
            "Milliseconds",
            {"JobType": "triage", "Result": "succeeded"},
        ),
    ]


def test_context_metrics_count_only_bounded_aggregate_metadata() -> None:
    _, sink = _telemetry()
    observer = HostedMetricObservers.build(sink, "worker").context_snapshots
    observer.record_snapshot(
        item_count=12, truncated=True, result="partial", provider="cloudwatch"
    )
    assert [record[0] for record in sink.records] == [
        "context_items_collected",
        "context_truncated_total",
    ]
    assert all(
        dimensions
        == {"Collector": "aggregate", "Provider": "cloudwatch", "Result": "partial"}
        for *_, dimensions in sink.records
    )


def test_outbox_metrics_are_aggregate_gauges() -> None:
    _, sink = _telemetry()
    HostedMetricObservers.build(sink, "dispatcher").outbox_backlog.record_backlog(
        pending_count=8,
        oldest_age_seconds=45,
        claimed_count=3,
    )
    assert [record[0] for record in sink.records] == [
        "outbox_pending_count",
        "outbox_oldest_pending_age_seconds",
        "outbox_claimed_count",
    ]
    assert all(dimensions == {"Result": "snapshot"} for *_, dimensions in sink.records)


def test_trace_attributes_fail_closed_and_collector_is_optional() -> None:
    with span("safe", **{"operation.name": "triage"}):
        pass
    with pytest.raises(ValueError, match="Unsafe trace attributes"):
        with span("unsafe", prompt="customer data"):
            pass


def test_slo_error_budget_and_burn_rate_math() -> None:
    thirty_days = 30 * 24 * 60 * 60
    assert error_budget_seconds(0.999, thirty_days) == pytest.approx(2592)
    assert burn_rate(0.0144, 0.999) == pytest.approx(14.4)
    assert burn_rate(0.006, 0.999) == pytest.approx(6)


def test_api_sli_denominator_excludes_health_and_correct_client_errors() -> None:
    assert not api_request_is_eligible("healthz", 200)
    assert not api_request_is_eligible("readyz", 503)
    assert not api_request_is_eligible("create_incident", 422)
    assert not api_request_is_eligible("list_incidents", 401)
    assert api_request_is_eligible("list_incidents", 200)
    assert api_request_is_eligible("list_incidents", 503)
