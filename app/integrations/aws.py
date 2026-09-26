"""Narrow AWS AssumeRole and capability-probe boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, ConnectTimeoutError, ReadTimeoutError

from app.domain.aws_integrations import AwsCapability, AwsVerificationError


class AwsIntegrationCallError(RuntimeError):
    def __init__(self, code: AwsVerificationError, summary: str) -> None:
        super().__init__(summary)
        self.code = code
        self.summary = summary


@dataclass(frozen=True, slots=True)
class AwsCallerIdentity:
    account_id: str
    arn: str


class AwsAssumedSession(Protocol):
    def caller_identity(self) -> AwsCallerIdentity: ...
    def probe(self, capability: AwsCapability, region: str) -> None: ...
    def describe_alarm(self, alarm_name: str, region: str) -> dict[str, Any] | None: ...
    def get_metric_data(
        self,
        *,
        region: str,
        query: dict[str, Any],
        start_time,
        end_time,
        max_datapoints: int,
    ) -> dict[str, Any]: ...
    def filter_log_events(
        self,
        *,
        region: str,
        log_group_name: str,
        start_time_ms: int,
        end_time_ms: int,
        limit: int,
        next_token: str | None = None,
    ) -> dict[str, Any]: ...


class AwsRoleAssumer(Protocol):
    def assume_role(
        self,
        *,
        role_arn: str,
        external_id: str,
        session_name: str,
        duration_seconds: int,
    ) -> AwsAssumedSession: ...


class Boto3AwsRoleAssumer:
    def __init__(
        self,
        sts_client: Any,
        *,
        source_role_arn: str | None = None,
        client_factory=None,
        config: Config | None = None,
    ) -> None:
        self._sts = sts_client
        self._source_role_arn = (source_role_arn or "").strip() or None
        self._client_factory = client_factory or _default_client_factory
        self._config = config or Config(
            connect_timeout=3.0,
            read_timeout=8.0,
            retries={"max_attempts": 3, "mode": "standard"},
        )

    def assume_role(
        self,
        *,
        role_arn: str,
        external_id: str,
        session_name: str,
        duration_seconds: int,
    ) -> AwsAssumedSession:
        try:
            sts = self._source_sts_client(session_name) if self._source_role_arn else self._sts
            response = sts.assume_role(
                RoleArn=role_arn,
                ExternalId=external_id,
                RoleSessionName=session_name,
                DurationSeconds=duration_seconds,
            )
            credentials = response["Credentials"]
            return _Boto3AssumedSession(
                credentials,
                self._client_factory,
                self._config,
            )
        except Exception as exc:
            raise _safe_aws_error(exc, operation="assume_role") from exc

    def _source_sts_client(self, session_name: str):
        response = self._sts.assume_role(
            RoleArn=self._source_role_arn,
            RoleSessionName=f"{session_name[:48]}-source",
            DurationSeconds=3600,
        )
        credentials = response["Credentials"]
        return self._client_factory(
            "sts",
            aws_access_key_id=credentials["AccessKeyId"],
            aws_secret_access_key=credentials["SecretAccessKey"],
            aws_session_token=credentials["SessionToken"],
            config=self._config,
        )


class _Boto3AssumedSession:
    def __init__(self, credentials: dict[str, Any], client_factory, config: Config) -> None:
        self._credentials = credentials
        self._client_factory = client_factory
        self._config = config

    def _client(self, service: str, region: str | None = None):
        return self._client_factory(
            service,
            region_name=region,
            aws_access_key_id=self._credentials["AccessKeyId"],
            aws_secret_access_key=self._credentials["SecretAccessKey"],
            aws_session_token=self._credentials["SessionToken"],
            config=self._config,
        )

    def caller_identity(self) -> AwsCallerIdentity:
        try:
            response = self._client("sts").get_caller_identity()
            return AwsCallerIdentity(str(response["Account"]), str(response["Arn"]))
        except Exception as exc:
            raise _safe_aws_error(exc, operation="identity") from exc

    def probe(self, capability: AwsCapability, region: str) -> None:
        try:
            if capability is AwsCapability.CLOUDWATCH_ALARMS_READ:
                self._client("cloudwatch", region).describe_alarms(MaxRecords=1)
            elif capability is AwsCapability.CLOUDWATCH_METRICS_READ:
                self._client("cloudwatch", region).list_metrics(MaxResults=1)
            elif capability is AwsCapability.CLOUDWATCH_LOGS_READ:
                self._client("logs", region).describe_log_groups(limit=1)
            else:
                raise ValueError("Unsupported AWS capability")
        except Exception as exc:
            raise _safe_aws_error(exc, operation=capability.value) from exc

    def describe_alarm(self, alarm_name: str, region: str) -> dict[str, Any] | None:
        try:
            response = self._client("cloudwatch", region).describe_alarms(
                AlarmNames=[alarm_name], MaxRecords=1
            )
            alarms = [*response.get("MetricAlarms", []), *response.get("CompositeAlarms", [])]
            return dict(alarms[0]) if alarms else None
        except Exception as exc:
            raise _safe_aws_error(exc, operation="cloudwatch:DescribeAlarms") from exc

    def get_metric_data(
        self,
        *,
        region: str,
        query: dict[str, Any],
        start_time,
        end_time,
        max_datapoints: int,
    ) -> dict[str, Any]:
        try:
            return dict(
                self._client("cloudwatch", region).get_metric_data(
                    MetricDataQueries=[query],
                    StartTime=start_time,
                    EndTime=end_time,
                    ScanBy="TimestampAscending",
                    MaxDatapoints=max_datapoints,
                )
            )
        except Exception as exc:
            raise _safe_aws_error(exc, operation="cloudwatch:GetMetricData") from exc

    def filter_log_events(
        self,
        *,
        region: str,
        log_group_name: str,
        start_time_ms: int,
        end_time_ms: int,
        limit: int,
        next_token: str | None = None,
    ) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "logGroupName": log_group_name,
            "startTime": start_time_ms,
            "endTime": end_time_ms,
            "limit": limit,
            "interleaved": True,
        }
        if next_token:
            parameters["nextToken"] = next_token
        try:
            return dict(self._client("logs", region).filter_log_events(**parameters))
        except Exception as exc:
            raise _safe_aws_error(exc, operation="logs:FilterLogEvents") from exc


def create_sts_client(
    *,
    region: str,
    endpoint_url: str | None = None,
    connect_timeout_seconds: float = 3.0,
    read_timeout_seconds: float = 8.0,
    max_attempts: int = 3,
):
    import boto3

    return boto3.client(
        "sts",
        region_name=region,
        endpoint_url=endpoint_url,
        config=Config(
            connect_timeout=connect_timeout_seconds,
            read_timeout=read_timeout_seconds,
            retries={"max_attempts": max_attempts, "mode": "standard"},
        ),
    )


def _default_client_factory(service: str, **kwargs):
    import boto3

    return boto3.client(service, **kwargs)


def _safe_aws_error(exc: Exception, *, operation: str) -> AwsIntegrationCallError:
    if isinstance(exc, ClientError):
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in {"Throttling", "ThrottlingException", "TooManyRequestsException"}:
            return AwsIntegrationCallError(AwsVerificationError.THROTTLED, "AWS throttled the verification request")
        if code in {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation"}:
            if operation == "assume_role":
                return AwsIntegrationCallError(AwsVerificationError.ROLE_NOT_ASSUMABLE, "AIRA could not assume the configured role")
            mapping = {
                AwsCapability.CLOUDWATCH_ALARMS_READ.value: (AwsVerificationError.CLOUDWATCH_PERMISSION_MISSING, "cloudwatch:DescribeAlarms is not permitted"),
                AwsCapability.CLOUDWATCH_METRICS_READ.value: (AwsVerificationError.METRICS_PERMISSION_MISSING, "cloudwatch:ListMetrics is not permitted"),
                AwsCapability.CLOUDWATCH_LOGS_READ.value: (AwsVerificationError.LOGS_PERMISSION_MISSING, "logs:DescribeLogGroups is not permitted"),
                "cloudwatch:DescribeAlarms": (AwsVerificationError.CLOUDWATCH_PERMISSION_MISSING, "cloudwatch:DescribeAlarms is not permitted"),
                "cloudwatch:GetMetricData": (AwsVerificationError.METRICS_PERMISSION_MISSING, "cloudwatch:GetMetricData is not permitted"),
                "logs:FilterLogEvents": (AwsVerificationError.LOGS_PERMISSION_MISSING, "logs:FilterLogEvents is not permitted"),
            }
            error, summary = mapping.get(operation, (AwsVerificationError.ACCESS_DENIED, "AWS denied the verification request"))
            return AwsIntegrationCallError(error, summary)
        if code in {"InvalidClientTokenId", "SignatureDoesNotMatch"}:
            return AwsIntegrationCallError(AwsVerificationError.EXTERNAL_ID_MISMATCH, "AWS rejected the trust configuration")
    if isinstance(exc, (ConnectTimeoutError, ReadTimeoutError, BotoCoreError, TimeoutError, OSError)):
        return AwsIntegrationCallError(AwsVerificationError.NETWORK_ERROR, "AWS verification could not reach the service")
    return AwsIntegrationCallError(AwsVerificationError.INTERNAL_ERROR, "AWS verification failed")
