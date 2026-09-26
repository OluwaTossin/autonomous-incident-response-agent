"""V3.24 typed usage, quota decisions, API summaries, and bounded metrics."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.hosted_usage import build_hosted_usage_router
from app.api.hosted_incidents import _http_error
from app.application.usage import UsageSummary
from app.domain.common import DomainInvariantError
from app.domain.events import UsageEvent
from app.domain.identifiers import CorrelationId, OrganizationId, UsageEventId, WorkspaceId
from app.domain.common import CorrelationContext, WorkspaceScope
from app.domain.usage import (
    QuotaDecision,
    QuotaExceeded,
    QuotaLimit,
    QuotaStatus,
    QuotaType,
    QuotaWindow,
    UsageType,
    quota_window,
)
from app.observability.metrics import InMemoryMetricSink, QuotaMetricObserver

NOW = datetime(2026, 9, 26, 10, 35, tzinfo=UTC)
ORG = OrganizationId("00000000-0000-4000-8000-000000000001")
WORKSPACE = WorkspaceId("00000000-0000-4000-8000-000000000002")


def test_usage_event_type_and_unit_are_allowlisted() -> None:
    event = UsageEvent(
        UsageEventId.new(),
        WorkspaceScope(ORG, WORKSPACE),
        UsageType.LLM_INPUT_TOKENS.value,
        12,
        "token",
        NOW,
        CorrelationContext(CorrelationId.new()),
        source="triage_run",
        source_reference="run-1",
    )
    assert event.quantity == 12
    with pytest.raises(DomainInvariantError, match="allowlisted"):
        UsageEvent(
            UsageEventId.new(),
            WorkspaceScope(ORG, WORKSPACE),
            "arbitrary_customer_event",
            1,
            "event",
            NOW,
            CorrelationContext(CorrelationId.new()),
        )
    with pytest.raises(DomainInvariantError, match="does not match"):
        UsageEvent(
            UsageEventId.new(),
            WorkspaceScope(ORG, WORKSPACE),
            UsageType.DOCUMENT_BYTES_STORED.value,
            1,
            "token",
            NOW,
            CorrelationContext(CorrelationId.new()),
        )


def test_quota_threshold_and_utc_window_are_deterministic() -> None:
    policy = QuotaLimit(
        QuotaType.TRIAGE_REQUESTS_PER_HOUR,
        10,
        warning_percent=80,
        window=QuotaWindow.UTC_HOUR,
    )
    assert policy.warning_threshold == 8
    start, reset = quota_window(NOW, policy.window)
    assert start.isoformat() == "2026-09-26T10:00:00+00:00"
    assert reset and reset.isoformat() == "2026-09-26T11:00:00+00:00"


def test_quota_metrics_have_no_tenant_dimensions() -> None:
    sink = InMemoryMetricSink()
    QuotaMetricObserver(sink).record(
        "quota_rejections", "concurrent_triage_runs", "triage", "rejected"
    )
    name, _, _, dimensions = sink.records[0]
    assert name == "quota_rejections_total"
    assert dimensions == {
        "QuotaType": "concurrent_triage_runs",
        "Operation": "triage",
        "Result": "rejected",
    }


def test_usage_summary_api_is_read_only_and_has_no_billing_semantics() -> None:
    decision = QuotaDecision(
        QuotaStatus.WARNING,
        QuotaType.TRIAGE_REQUESTS_PER_HOUR,
        8,
        0,
        10,
        2,
        1,
        datetime(2026, 9, 26, 11, tzinfo=UTC),
    )
    service = SimpleNamespace(
        workspace_summary=lambda *_: UsageSummary(ORG, WORKSPACE, NOW, (decision,))
    )
    app = FastAPI()
    app.include_router(build_hosted_usage_router(service, lambda: object()))
    response = TestClient(app).get(
        f"/v3/organizations/{ORG}/workspaces/{WORKSPACE}/usage"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["billing_enabled"] is False
    assert body["quotas"][0]["status"] == "warning"
    assert "price" not in str(body).lower()


def test_windowed_quota_error_maps_to_429_with_truthful_retry_after() -> None:
    reset_at = datetime.now(UTC) + timedelta(minutes=5)
    error = _http_error(
        QuotaExceeded(
            QuotaDecision(
                QuotaStatus.REJECTED,
                QuotaType.TRIAGE_REQUESTS_PER_HOUR,
                10,
                1,
                10,
                0,
                4,
                reset_at,
            )
        )
    )
    assert error.status_code == 429
    assert error.detail["code"] == "quota_exceeded"
    assert error.detail["reset_at"] == reset_at.isoformat()
    assert 1 <= int(error.headers["Retry-After"]) <= 300
