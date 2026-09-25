"""Bounded CloudWatch incident-context collection tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.application.incident_context import (
    AwsIncidentContextBinding,
    ContextCollectionPolicy,
    ContextEnrichmentFailure,
    IncidentContextEnricher,
    project_context,
    redact_text,
)
from app.application.jobs import JobCancellationRequested
from app.domain.alert_ingestion import (
    AlertEventReceipt,
    AlertReceiptStatus,
    CloudWatchAlarmValue,
)
from app.domain.aws_integrations import (
    AwsCapability,
    AwsCapabilityCheck,
    AwsIntegration,
    AwsIntegrationState,
    AwsVerificationResult,
    AwsVerificationError,
)
from app.domain.common import (
    ActorKind,
    ActorReference,
    CorrelationContext,
    WorkspaceScope,
)
from app.domain.identifiers import (
    AlertReceiptId,
    CorrelationId,
    IncidentId,
    IntegrationId,
    JobId,
    OrganizationId,
    TriageRunId,
    WorkspaceId,
)
from app.domain.incident_context import CollectorStatus, ContextItemType
from app.domain.incidents import (
    Incident,
    IncidentReference,
    IncidentSource,
    IncidentState,
    TriageRun,
    TriageRunState,
)
from app.integrations.aws import AwsIntegrationCallError, AwsCallerIdentity
from app.models.incident import IncidentPayload

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
ORG = OrganizationId("10000000-0000-4000-8000-000000000001")
WORKSPACE = WorkspaceId("10000000-0000-4000-8000-000000000002")
INCIDENT = IncidentId("10000000-0000-4000-8000-000000000003")
RUN = TriageRunId("10000000-0000-4000-8000-000000000004")
INTEGRATION = IntegrationId("10000000-0000-4000-8000-000000000005")
ALARM_ARN = "arn:aws:cloudwatch:eu-west-2:123456789012:alarm:checkout-errors"


def _actor() -> ActorReference:
    return ActorReference(ActorKind.SYSTEM, system_name="aira-worker")


def _binding(
    *, log_groups=("/aws/lambda/checkout",), capabilities=tuple(AwsCapability)
):
    scope = WorkspaceScope(ORG, WORKSPACE)
    incident = Incident(
        INCIDENT,
        scope,
        IncidentPayload(
            alert_title="Checkout errors",
            service_name="checkout",
            environment="eu-west-2",
            logs="Alarm entered ALARM",
            metric_summary="Error rate high",
            time_of_occurrence=NOW.isoformat(),
        ),
        IncidentSource("aws.cloudwatch", "alarm_state_change", NOW, "event-1"),
        IncidentState.OPEN,
        _actor(),
        NOW,
        NOW,
        CorrelationContext(
            CorrelationId.new(), incident_id=INCIDENT, triage_run_id=RUN
        ),
    )
    run = TriageRun(
        RUN,
        scope,
        IncidentReference(INCIDENT, scope),
        TriageRunState.RUNNING,
        _actor(),
        NOW,
        NOW,
        CorrelationContext(
            CorrelationId.new(),
            incident_id=INCIDENT,
            triage_run_id=RUN,
            job_id=JobId.new(),
        ),
        started_at=NOW,
        state_version=2,
    )
    checks = tuple(
        AwsCapabilityCheck(capability, "eu-west-2", True) for capability in capabilities
    )
    verification = AwsVerificationResult(True, True, checks, NOW)
    integration = AwsIntegration(
        INTEGRATION,
        scope,
        "Production",
        "123456789012",
        "x" * 32,
        ("eu-west-2",),
        AwsIntegrationState.READY,
        _actor(),
        NOW,
        NOW,
        role_arn="arn:aws:iam::123456789012:role/AiraReadRole",
        verification=verification,
        log_group_names=log_groups,
    )
    receipt = AlertEventReceipt(
        AlertReceiptId.new(),
        scope,
        INTEGRATION,
        "event-1",
        "a" * 64,
        ALARM_ARN,
        "b" * 64,
        "checkout-errors",
        "123456789012",
        "eu-west-2",
        CloudWatchAlarmValue.ALARM,
        CloudWatchAlarmValue.OK,
        NOW,
        NOW,
        AlertReceiptStatus.ACCEPTED,
        _actor(),
        incident_id=INCIDENT,
        triage_run_id=RUN,
    )
    return AwsIncidentContextBinding(incident, run, receipt, integration)


class Session:
    def __init__(
        self,
        *,
        alarm=None,
        log_pages=None,
        account="123456789012",
        logs_error=None,
    ):
        self.alarm = alarm or {
            "AlarmArn": ALARM_ARN,
            "Namespace": "AWS/Lambda",
            "MetricName": "Errors",
            "Dimensions": [{"Name": "FunctionName", "Value": "checkout"}],
            "Statistic": "Sum",
            "Period": 60,
            "Threshold": 5,
            "ComparisonOperator": "GreaterThanThreshold",
        }
        self.log_pages = list(log_pages or [])
        self.account = account
        self.logs_error = logs_error
        self.calls = []

    def caller_identity(self):
        return AwsCallerIdentity(
            self.account,
            f"arn:aws:sts::{self.account}:assumed-role/AiraReadRole/context",
        )

    def describe_alarm(self, alarm_name, region):
        self.calls.append(("alarm", alarm_name, region))
        return self.alarm

    def get_metric_data(self, **values):
        self.calls.append(("metric", values))
        return {
            "MetricDataResults": [
                {
                    "Label": "Errors",
                    "Timestamps": [NOW - timedelta(minutes=1), NOW],
                    "Values": [2.0, 8.0],
                }
            ]
        }

    def filter_log_events(self, **values):
        self.calls.append(("logs", values))
        if self.logs_error is not None:
            raise self.logs_error
        if self.log_pages:
            return self.log_pages.pop(0)
        return {"events": []}


class Assumer:
    def __init__(self, session):
        self.session = session
        self.values = None

    def assume_role(self, **values):
        self.values = values
        if isinstance(self.session, Exception):
            raise self.session
        return self.session


def test_collection_is_alarm_bound_allowlisted_redacted_and_projected() -> None:
    session = Session(
        log_pages=[
            {
                "events": [
                    {
                        "timestamp": int(NOW.timestamp() * 1000),
                        "logStreamName": "2026/09/25/[$LATEST]abc",
                        "message": '{"authorization":"Bearer secret-value","error":"timeout"}',
                    }
                ]
            }
        ]
    )
    assumer = Assumer(session)
    snapshot = IncidentContextEnricher(assumer, clock=lambda: NOW).collect(
        _binding(), cancellation_requested=lambda: False
    )

    assert assumer.values["duration_seconds"] == 900
    assert session.calls[0] == ("alarm", "checkout-errors", "eu-west-2")
    log_call = next(call[1] for call in session.calls if call[0] == "logs")
    assert log_call["log_group_name"] == "/aws/lambda/checkout"
    assert log_call["region"] == "eu-west-2"
    log_item = next(item for item in snapshot.items if item.type is ContextItemType.LOG)
    assert "secret-value" not in log_item.content["message"]
    assert "[REDACTED]" in log_item.content["message"]
    projected = project_context({"logs": "alarm", "metric_summary": "high"}, snapshot)
    assert "CloudWatch incident context" in projected["logs"]
    assert str(snapshot.id) == projected["operational_context"]["snapshot_id"]


def test_no_log_configuration_does_not_discover_log_groups() -> None:
    session = Session()
    snapshot = IncidentContextEnricher(Assumer(session), clock=lambda: NOW).collect(
        _binding(log_groups=()), cancellation_requested=lambda: False
    )

    assert not any(call[0] == "logs" for call in session.calls)
    logs = next(item for item in snapshot.diagnostics if item.collector == "logs")
    assert logs.status is CollectorStatus.NOT_CONFIGURED


def test_unsupported_metric_alarm_is_partial_without_arbitrary_expression() -> None:
    session = Session(
        alarm={
            "AlarmArn": ALARM_ARN,
            "Metrics": [
                {
                    "Id": "unsafe",
                    "Expression": "SEARCH('{AWS/EC2} MetricName=CPUUtilization')",
                }
            ],
        }
    )
    snapshot = IncidentContextEnricher(Assumer(session), clock=lambda: NOW).collect(
        _binding(log_groups=()), cancellation_requested=lambda: False
    )

    assert not any(call[0] == "metric" for call in session.calls)
    metric = next(item for item in snapshot.diagnostics if item.collector == "metrics")
    assert metric.status is CollectorStatus.UNSUPPORTED
    assert snapshot.status.value == "partial"


def test_provider_call_and_log_byte_budgets_stop_pagination() -> None:
    pages = [
        {
            "events": [
                {
                    "timestamp": int(NOW.timestamp() * 1000),
                    "logStreamName": "stream",
                    "message": "x" * 100,
                }
            ],
            "nextToken": "more",
        }
    ]
    policy = ContextCollectionPolicy(
        max_provider_calls=3,
        max_log_bytes=20,
        max_log_events=10,
    )
    session = Session(log_pages=pages)
    snapshot = IncidentContextEnricher(
        Assumer(session), policy=policy, clock=lambda: NOW
    ).collect(_binding(), cancellation_requested=lambda: False)

    assert len([call for call in session.calls if call[0] == "logs"]) == 1
    assert snapshot.truncated is True


def test_assume_role_transient_failure_is_retryable() -> None:
    failure = AwsIntegrationCallError(
        code=AwsVerificationError.THROTTLED,
        summary="AWS throttled the request",
    )
    with pytest.raises(ContextEnrichmentFailure) as raised:
        IncidentContextEnricher(Assumer(failure)).collect(
            _binding(), cancellation_requested=lambda: False
        )
    assert raised.value.retryable is True
    assert raised.value.category.value == "transient"


def test_optional_logs_failure_keeps_metric_context_and_marks_partial() -> None:
    session = Session(
        logs_error=AwsIntegrationCallError(
            AwsVerificationError.NETWORK_ERROR,
            "CloudWatch Logs was temporarily unavailable",
        )
    )
    snapshot = IncidentContextEnricher(Assumer(session), clock=lambda: NOW).collect(
        _binding(), cancellation_requested=lambda: False
    )

    assert any(item.type is ContextItemType.METRIC for item in snapshot.items)
    assert snapshot.status.value == "partial"
    logs = next(item for item in snapshot.diagnostics if item.collector == "logs")
    assert logs.status is CollectorStatus.FAILED
    assert "temporarily unavailable" in (logs.summary or "")


def test_total_context_budget_is_applied_before_persistence_projection() -> None:
    snapshot = IncidentContextEnricher(
        Assumer(Session()),
        policy=ContextCollectionPolicy(max_context_chars=10),
        clock=lambda: NOW,
    ).collect(_binding(), cancellation_requested=lambda: False)

    assert snapshot.items == ()
    assert snapshot.truncated is True
    projected = project_context({"logs": "original"}, snapshot)
    assert projected["logs"] == "original"


def test_cancellation_is_checked_before_assume_role() -> None:
    assumer = Assumer(Session())
    with pytest.raises(JobCancellationRequested, match="cancellation"):
        IncidentContextEnricher(assumer).collect(
            _binding(), cancellation_requested=lambda: True
        )
    assert assumer.values is None


@pytest.mark.parametrize(
    "value",
    [
        "Authorization: Bearer abcdefghijklmnop",
        "password=hunter2",
        "AKIAABCDEFGHIJKLMNOP",
        "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----",
        '{"cookie":"session-secret","nested":{"api_key":"key-secret"}}',
    ],
)
def test_redaction_removes_common_secret_shapes(value: str) -> None:
    redacted = redact_text(value)
    assert "secret" not in redacted.lower() or "[redacted]" in redacted.lower()
    assert "hunter2" not in redacted
    assert "AKIAABCDEFGHIJKLMNOP" not in redacted
