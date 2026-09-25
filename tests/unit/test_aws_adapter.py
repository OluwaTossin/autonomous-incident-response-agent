"""Injected boto3 AWS verification adapter tests without live AWS."""

from __future__ import annotations

import pytest
from botocore.exceptions import ClientError, ConnectTimeoutError

from app.domain.aws_integrations import AwsCapability, AwsVerificationError
from app.integrations.aws import Boto3AwsRoleAssumer, AwsIntegrationCallError


class Sts:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def assume_role(self, **values):
        self.calls.append(values)
        if self.error:
            raise self.error
        return {
            "Credentials": {
                "AccessKeyId": "temporary-access",
                "SecretAccessKey": "temporary-secret",
                "SessionToken": "temporary-token",
            }
        }


class Client:
    def __init__(self, service, error=None):
        self.service = service
        self.error = error
        self.calls = []

    def _call(self, name, values):
        self.calls.append((name, values))
        if self.error:
            raise self.error

    def get_caller_identity(self):
        self._call("get_caller_identity", {})
        return {
            "Account": "123456789012",
            "Arn": "arn:aws:sts::123456789012:assumed-role/aira-read/session",
        }

    def describe_alarms(self, **values):
        self._call("describe_alarms", values)
        return {"MetricAlarms": [{"AlarmName": "known-alarm"}]}

    def get_metric_data(self, **values):
        self._call("get_metric_data", values)
        return {"MetricDataResults": []}

    def filter_log_events(self, **values):
        self._call("filter_log_events", values)
        return {"events": []}

    def list_metrics(self, **values):
        self._call("list_metrics", values)

    def describe_log_groups(self, **values):
        self._call("describe_log_groups", values)


def _client_error(code):
    return ClientError(
        {"Error": {"Code": code, "Message": "raw provider detail"}}, "op"
    )


def test_assume_role_encapsulates_credentials_and_uses_bounded_inputs() -> None:
    sts = Sts()
    created = []

    def factory(service, **values):
        created.append((service, values))
        return Client(service)

    assumer = Boto3AwsRoleAssumer(sts, client_factory=factory)
    session = assumer.assume_role(
        role_arn="arn:aws:iam::123456789012:role/aira-read",
        external_id="external-id",
        session_name="aira-verify",
        duration_seconds=900,
    )
    identity = session.caller_identity()
    session.probe(AwsCapability.CLOUDWATCH_ALARMS_READ, "eu-west-2")
    session.probe(AwsCapability.CLOUDWATCH_METRICS_READ, "eu-west-2")
    session.probe(AwsCapability.CLOUDWATCH_LOGS_READ, "eu-west-2")

    assert identity.account_id == "123456789012"
    assert sts.calls[0]["ExternalId"] == "external-id"
    assert sts.calls[0]["DurationSeconds"] == 900
    assert [service for service, _ in created] == [
        "sts",
        "cloudwatch",
        "cloudwatch",
        "logs",
    ]
    assert all(
        values["aws_session_token"] == "temporary-token" for _, values in created
    )
    assert not hasattr(session, "access_key_id")


@pytest.mark.parametrize(
    "code,expected",
    [
        ("AccessDenied", AwsVerificationError.ROLE_NOT_ASSUMABLE),
        ("ThrottlingException", AwsVerificationError.THROTTLED),
        ("InvalidClientTokenId", AwsVerificationError.EXTERNAL_ID_MISMATCH),
    ],
)
def test_assume_role_errors_are_safely_classified(code, expected) -> None:
    assumer = Boto3AwsRoleAssumer(Sts(_client_error(code)))
    with pytest.raises(AwsIntegrationCallError) as raised:
        assumer.assume_role(
            role_arn="arn:aws:iam::123456789012:role/aira-read",
            external_id="external-id",
            session_name="aira-verify",
            duration_seconds=900,
        )
    assert raised.value.code is expected
    assert "raw provider detail" not in raised.value.summary


def test_capability_access_denied_and_network_errors_are_safe() -> None:
    def denied_factory(service, **values):
        return Client(service, _client_error("AccessDenied"))

    session = Boto3AwsRoleAssumer(Sts(), client_factory=denied_factory).assume_role(
        role_arn="arn:aws:iam::123456789012:role/aira-read",
        external_id="external-id",
        session_name="aira-verify",
        duration_seconds=900,
    )
    with pytest.raises(AwsIntegrationCallError) as raised:
        session.probe(AwsCapability.CLOUDWATCH_LOGS_READ, "eu-west-2")
    assert raised.value.code is AwsVerificationError.LOGS_PERMISSION_MISSING

    assumer = Boto3AwsRoleAssumer(Sts(ConnectTimeoutError(endpoint_url="https://sts")))
    with pytest.raises(AwsIntegrationCallError) as raised:
        assumer.assume_role(
            role_arn="arn:aws:iam::123456789012:role/aira-read",
            external_id="external-id",
            session_name="aira-verify",
            duration_seconds=900,
        )
    assert raised.value.code is AwsVerificationError.NETWORK_ERROR


def test_context_methods_keep_provider_calls_narrow_and_bounded() -> None:
    clients = {}

    def factory(service, **values):
        client = Client(service)
        clients[service] = client
        return client

    session = Boto3AwsRoleAssumer(Sts(), client_factory=factory).assume_role(
        role_arn="arn:aws:iam::123456789012:role/aira-read",
        external_id="external-id",
        session_name="aira-context",
        duration_seconds=900,
    )
    alarm = session.describe_alarm("known-alarm", "eu-west-2")
    session.get_metric_data(
        region="eu-west-2",
        query={"Id": "alarmmetric", "MetricStat": {}},
        start_time="start",
        end_time="end",
        max_datapoints=120,
    )
    session.filter_log_events(
        region="eu-west-2",
        log_group_name="/aws/lambda/checkout",
        start_time_ms=1,
        end_time_ms=2,
        limit=100,
    )

    assert alarm == {"AlarmName": "known-alarm"}
    assert clients["cloudwatch"].calls[-1][1]["MaxDatapoints"] == 120
    assert clients["logs"].calls[-1][1]["logGroupName"] == "/aws/lambda/checkout"
    assert "logGroupNamePrefix" not in clients["logs"].calls[-1][1]
