"""Bounded CloudWatch context collection before hosted triage execution."""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from app.domain.alert_ingestion import AlertEventReceipt
from app.domain.aws_integrations import (
    AwsCapability,
    AwsIntegration,
    AwsIntegrationState,
    AwsVerificationError,
)
from app.domain.identifiers import IncidentContextItemId, IncidentContextSnapshotId
from app.domain.incident_context import (
    CollectorDiagnostic,
    CollectorStatus,
    ContextCollectionStatus,
    ContextItemType,
    IncidentContextItem,
    IncidentContextSnapshot,
)
from app.domain.incidents import Incident, TriageRun
from app.domain.operations import JobErrorCategory
from app.integrations.aws import AwsIntegrationCallError, AwsRoleAssumer

_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "authorization",
        "cookie",
        "set-cookie",
        "api_key",
        "apikey",
        "access_key",
        "session",
        "session_token",
    }
)
_TEXT_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]{8,}"),
    re.compile(
        r"(?i)((?:password|passwd|secret|token|api[_-]?key|access[_-]?key|cookie)\s*[:=]\s*)[^\s,;]+"
    ),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
    ),
)
_SUPPORTED_STATISTICS = frozenset(
    {"Average", "Sum", "Minimum", "Maximum", "SampleCount"}
)


@dataclass(frozen=True, slots=True)
class ContextCollectionPolicy:
    metric_lookback: timedelta = timedelta(minutes=15)
    log_lookback: timedelta = timedelta(minutes=15)
    forward_window: timedelta = timedelta(minutes=2)
    max_metric_points: int = 120
    max_log_events: int = 100
    max_log_bytes: int = 65_536
    max_provider_calls: int = 8
    max_context_chars: int = 80_000
    max_message_chars: int = 4_000
    policy_version: str = "cloudwatch-context-v1"

    def __post_init__(self) -> None:
        if self.metric_lookback <= timedelta(0) or self.log_lookback <= timedelta(0):
            raise ValueError("Context lookback must be positive")
        if self.forward_window < timedelta(0) or self.forward_window > timedelta(
            minutes=15
        ):
            raise ValueError("Context forward window is invalid")
        for value in (
            self.max_metric_points,
            self.max_log_events,
            self.max_log_bytes,
            self.max_provider_calls,
            self.max_context_chars,
            self.max_message_chars,
        ):
            if value < 1:
                raise ValueError("Context collection bounds must be positive")


@dataclass(frozen=True, slots=True)
class AwsIncidentContextBinding:
    incident: Incident
    run: TriageRun
    receipt: AlertEventReceipt
    integration: AwsIntegration


@dataclass(frozen=True, slots=True)
class ContextEnrichmentFailure(RuntimeError):
    code: str
    category: JobErrorCategory
    retryable: bool
    summary: str

    def __str__(self) -> str:
        return self.summary


class ContextEnrichmentObserver(Protocol):
    def record(self, event: str, duration_ms: int, outcome: str) -> None: ...


class NoopContextEnrichmentObserver:
    def record(self, event: str, duration_ms: int, outcome: str) -> None:
        return None


class IncidentContextEnricher:
    """Collect CloudWatch evidence from one persisted alarm binding."""

    def __init__(
        self,
        role_assumer: AwsRoleAssumer,
        *,
        policy: ContextCollectionPolicy = ContextCollectionPolicy(),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
        observer: ContextEnrichmentObserver = NoopContextEnrichmentObserver(),
    ) -> None:
        self._role_assumer = role_assumer
        self._policy = policy
        self._clock = clock
        self._monotonic = monotonic
        self._observer = observer

    def collect(
        self,
        binding: AwsIncidentContextBinding,
        *,
        cancellation_requested: Callable[[], bool],
    ) -> IncidentContextSnapshot:
        started = self._monotonic()
        self._validate_binding(binding)
        self._cancel(cancellation_requested)
        integration = binding.integration
        try:
            session = self._role_assumer.assume_role(
                role_arn=integration.role_arn or "",
                external_id=integration.external_id,
                session_name=f"aira-context-{str(binding.run.id)[:12]}",
                duration_seconds=900,
            )
            identity = session.caller_identity()
        except AwsIntegrationCallError as exc:
            self._observer.record(
                "context_enrichment_failed", self._duration(started), "failed"
            )
            raise _provider_failure(exc, "aws_context_role_unavailable") from exc
        if (
            identity.account_id != integration.aws_account_id
            or not _identity_matches_role(identity.arn, integration.role_arn or "")
        ):
            raise ContextEnrichmentFailure(
                "aws_context_account_mismatch",
                JobErrorCategory.AUTHORIZATION,
                False,
                "Assumed AWS identity does not match the configured integration",
            )

        self._cancel(cancellation_requested)
        receipt = binding.receipt
        metric_start = receipt.observed_at - self._policy.metric_lookback
        log_start = receipt.observed_at - self._policy.log_lookback
        window_start = min(metric_start, log_start)
        window_end = receipt.observed_at + self._policy.forward_window
        snapshot_id = IncidentContextSnapshotId.new()
        raw_items: list[tuple[ContextItemType, str, datetime, dict[str, Any], bool]] = [
            (
                ContextItemType.ALARM,
                receipt.alarm_identity,
                receipt.observed_at,
                {
                    "alarm_name": receipt.alarm_name,
                    "alarm_arn": receipt.alarm_identity,
                    "state": receipt.state.value,
                    "previous_state": receipt.previous_state.value,
                    "region": receipt.region,
                },
                False,
            )
        ]
        diagnostics: list[CollectorDiagnostic] = [
            CollectorDiagnostic("alarm", CollectorStatus.SUCCEEDED)
        ]
        collection_truncated = False
        calls = 0
        try:
            alarm = session.describe_alarm(receipt.alarm_name, receipt.region)
            calls += 1
        except AwsIntegrationCallError as exc:
            alarm = None
            diagnostics[0] = _diagnostic("alarm", exc)

        self._cancel(cancellation_requested)
        if _capability_verified(
            integration, AwsCapability.CLOUDWATCH_METRICS_READ, receipt.region
        ):
            try:
                query = _metric_query(alarm, receipt)
                if query is None:
                    diagnostics.append(
                        CollectorDiagnostic(
                            "metrics",
                            CollectorStatus.UNSUPPORTED,
                            "unsupported_alarm_metric",
                            "Alarm metric configuration is unavailable or unsupported",
                        )
                    )
                elif calls >= self._policy.max_provider_calls:
                    diagnostics.append(_budget_diagnostic("metrics"))
                else:
                    response = session.get_metric_data(
                        region=receipt.region,
                        query=query,
                        start_time=metric_start,
                        end_time=window_end,
                        max_datapoints=self._policy.max_metric_points,
                    )
                    calls += 1
                    raw_items.extend(
                        _normalize_metric(
                            response,
                            alarm or {},
                            receipt,
                            metric_start,
                            window_end,
                            self._policy.max_metric_points,
                        )
                    )
                    diagnostics.append(
                        CollectorDiagnostic("metrics", CollectorStatus.SUCCEEDED)
                    )
            except AwsIntegrationCallError as exc:
                diagnostics.append(_diagnostic("metrics", exc))
        else:
            diagnostics.append(
                CollectorDiagnostic(
                    "metrics",
                    CollectorStatus.FAILED,
                    "metrics_capability_unverified",
                    "CloudWatch metrics capability is not verified for the incident region",
                )
            )

        self._cancel(cancellation_requested)
        log_groups = integration.log_group_names
        if not log_groups:
            diagnostics.append(
                CollectorDiagnostic("logs", CollectorStatus.NOT_CONFIGURED)
            )
        elif not _capability_verified(
            integration, AwsCapability.CLOUDWATCH_LOGS_READ, receipt.region
        ):
            diagnostics.append(
                CollectorDiagnostic(
                    "logs",
                    CollectorStatus.FAILED,
                    "logs_capability_unverified",
                    "CloudWatch Logs capability is not verified for the incident region",
                )
            )
        else:
            try:
                log_items, calls, log_truncated = self._collect_logs(
                    session,
                    receipt.region,
                    log_groups,
                    log_start,
                    window_end,
                    calls,
                    cancellation_requested,
                )
                raw_items.extend(log_items)
                diagnostics.append(
                    CollectorDiagnostic("logs", CollectorStatus.SUCCEEDED)
                )
                if log_truncated:
                    collection_truncated = True
            except AwsIntegrationCallError as exc:
                diagnostics.append(_diagnostic("logs", exc))

        items, budget_truncated = _bound_items(
            snapshot_id,
            binding,
            raw_items,
            self._policy.max_context_chars,
        )
        partial = any(
            item.status in {CollectorStatus.FAILED, CollectorStatus.UNSUPPORTED}
            for item in diagnostics
        )
        snapshot = IncidentContextSnapshot(
            id=snapshot_id,
            scope=binding.run.scope,
            incident_id=binding.incident.id,
            triage_run_id=binding.run.id,
            integration_id=integration.id,
            provider="aws.cloudwatch",
            region=receipt.region,
            window_start=window_start,
            window_end=window_end,
            collected_at=self._clock(),
            status=(
                ContextCollectionStatus.PARTIAL
                if partial
                else ContextCollectionStatus.COMPLETE
            ),
            policy_version=self._policy.policy_version,
            diagnostics=tuple(diagnostics),
            items=items,
            truncated=(
                collection_truncated
                or budget_truncated
                or any(item.truncated for item in items)
            ),
        )
        outcome = "partial" if partial else "succeeded"
        self._observer.record(
            f"context_enrichment_{outcome}", self._duration(started), outcome
        )
        return snapshot

    def _collect_logs(
        self,
        session,
        region: str,
        log_groups: tuple[str, ...],
        start: datetime,
        end: datetime,
        calls: int,
        cancellation_requested: Callable[[], bool],
    ) -> tuple[
        list[tuple[ContextItemType, str, datetime, dict[str, Any], bool]], int, bool
    ]:
        events: list[tuple[datetime, str, str, str]] = []
        byte_count = 0
        truncated = False
        for group in log_groups:
            token = None
            while len(events) < self._policy.max_log_events:
                self._cancel(cancellation_requested)
                if calls >= self._policy.max_provider_calls:
                    truncated = True
                    break
                response = session.filter_log_events(
                    region=region,
                    log_group_name=group,
                    start_time_ms=int(start.timestamp() * 1000),
                    end_time_ms=int(end.timestamp() * 1000),
                    limit=min(100, self._policy.max_log_events - len(events)),
                    next_token=token,
                )
                calls += 1
                for raw in response.get("events", []):
                    message = redact_text(str(raw.get("message", "")))
                    encoded = message.encode("utf-8")
                    if byte_count + len(encoded) > self._policy.max_log_bytes:
                        truncated = True
                        break
                    message = message[: self._policy.max_message_chars]
                    byte_count += len(message.encode("utf-8"))
                    observed = datetime.fromtimestamp(
                        int(raw.get("timestamp", 0)) / 1000, UTC
                    )
                    if observed < start or observed > end:
                        continue
                    events.append(
                        (
                            observed,
                            group,
                            redact_text(str(raw.get("logStreamName", "")))[:512],
                            message,
                        )
                    )
                next_token = response.get("nextToken")
                if truncated or not next_token or next_token == token:
                    break
                token = str(next_token)
            if truncated or len(events) >= self._policy.max_log_events:
                truncated = True
                break
        events.sort(key=lambda value: (abs((value[0] - end).total_seconds()), value[0]))
        normalized = [
            (
                ContextItemType.LOG,
                f"{group}:{stream}" if stream else group,
                observed,
                {
                    "timestamp": observed.isoformat(),
                    "log_group": group,
                    "log_stream": stream or None,
                    "message": message,
                    "region": region,
                },
                truncated,
            )
            for observed, group, stream, message in events[
                : self._policy.max_log_events
            ]
        ]
        return normalized, calls, truncated

    @staticmethod
    def _validate_binding(binding: AwsIncidentContextBinding) -> None:
        integration = binding.integration
        receipt = binding.receipt
        if binding.incident.source.provider != "aws.cloudwatch":
            raise ContextEnrichmentFailure(
                "unsupported_incident_source",
                JobErrorCategory.CONFIGURATION,
                False,
                "Incident is not eligible for AWS context collection",
            )
        if (
            integration.state is not AwsIntegrationState.READY
            or integration.role_arn is None
        ):
            raise ContextEnrichmentFailure(
                "aws_integration_not_ready",
                JobErrorCategory.CONFIGURATION,
                False,
                "AWS integration is not ready",
            )
        if (
            receipt.integration_id != integration.id
            or receipt.incident_id != binding.incident.id
        ):
            raise ContextEnrichmentFailure(
                "aws_context_binding_invalid",
                JobErrorCategory.AUTHORIZATION,
                False,
                "Persisted AWS incident binding is invalid",
            )
        if receipt.region not in integration.enabled_regions:
            raise ContextEnrichmentFailure(
                "aws_context_region_disabled",
                JobErrorCategory.CONFIGURATION,
                False,
                "Incident region is not configured",
            )
        if not _capability_verified(
            integration, AwsCapability.CLOUDWATCH_ALARMS_READ, receipt.region
        ):
            raise ContextEnrichmentFailure(
                "alarm_capability_unverified",
                JobErrorCategory.CONFIGURATION,
                False,
                "CloudWatch alarm capability is not verified for the incident region",
            )

    @staticmethod
    def _cancel(cancellation_requested: Callable[[], bool]) -> None:
        if cancellation_requested():
            from app.application.jobs import JobCancellationRequested

            raise JobCancellationRequested("Job cancellation was requested")

    def _duration(self, started: float) -> int:
        return int((self._monotonic() - started) * 1000)


def project_context(
    payload: dict[str, object], snapshot: IncidentContextSnapshot
) -> dict[str, object]:
    """Project already-redacted bounded context into the legacy triage input shape."""
    result = dict(payload)
    metrics = [
        item.content for item in snapshot.items if item.type is ContextItemType.METRIC
    ]
    logs = [item.content for item in snapshot.items if item.type is ContextItemType.LOG]
    if metrics:
        rendered = json.dumps(
            metrics, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        result["metric_summary"] = _append(
            str(result.get("metric_summary", "")), rendered
        )
    if logs:
        rendered = "\n".join(
            f"[{item.get('timestamp', '')}] {item.get('log_group', '')}: {item.get('message', '')}"
            for item in logs
        )
        result["logs"] = _append(str(result.get("logs", "")), rendered)
    result["operational_context"] = {
        "snapshot_id": str(snapshot.id),
        "provider": snapshot.provider,
        "region": snapshot.region,
        "status": snapshot.status.value,
        "truncated": snapshot.truncated,
    }
    return result


def redact_value(value: Any, *, depth: int = 0) -> Any:
    """Bounded key-aware and textual redaction; this is not a full DLP system."""
    if depth >= 8:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        result = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 100:
                result["_truncated"] = True
                break
            normalized = str(key).lower().replace("-", "_")
            result[str(key)] = (
                "[REDACTED]"
                if normalized in _SENSITIVE_KEYS
                else redact_value(item, depth=depth + 1)
            )
        return result
    if isinstance(value, list):
        return [redact_value(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(value: str) -> str:
    text = value
    if text.lstrip().startswith(("{", "[")) and len(text) <= 100_000:
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            pass
        else:
            text = json.dumps(redact_value(parsed), sort_keys=True, ensure_ascii=True)
    for pattern in _TEXT_PATTERNS:
        text = pattern.sub(
            lambda match: (match.group(1) if match.lastindex else "") + "[REDACTED]",
            text,
        )
    return text


def _metric_query(
    alarm: dict[str, Any] | None, receipt: AlertEventReceipt
) -> dict[str, Any] | None:
    if not alarm or alarm.get("AlarmArn") != receipt.alarm_identity:
        return None
    if alarm.get("Metrics"):
        metrics = alarm["Metrics"]
        if (
            len(metrics) != 1
            or "MetricStat" not in metrics[0]
            or metrics[0].get("Expression")
        ):
            return None
        metric_stat = metrics[0]["MetricStat"]
    elif alarm.get("MetricName") and alarm.get("Namespace"):
        statistic = alarm.get("Statistic") or alarm.get("ExtendedStatistic")
        if statistic not in _SUPPORTED_STATISTICS and not re.fullmatch(
            r"p\d{1,2}(?:\.\d+)?", str(statistic)
        ):
            return None
        metric_stat = {
            "Metric": {
                "Namespace": alarm["Namespace"],
                "MetricName": alarm["MetricName"],
                "Dimensions": alarm.get("Dimensions", []),
            },
            "Period": alarm.get("Period", 60),
            "Stat": statistic,
        }
        if alarm.get("Unit"):
            metric_stat["Unit"] = alarm["Unit"]
    else:
        return None
    period = int(metric_stat.get("Period", 0))
    if period < 1 or period > 86_400:
        return None
    stat = str(metric_stat.get("Stat", ""))
    if stat not in _SUPPORTED_STATISTICS and not re.fullmatch(
        r"p\d{1,2}(?:\.\d+)?", stat
    ):
        return None
    query = {"Id": "alarmmetric", "MetricStat": metric_stat, "ReturnData": True}
    return redact_value(query)


def _normalize_metric(response, alarm, receipt, start, end, limit):
    results = response.get("MetricDataResults", [])[:1]
    if not results:
        return []
    result = results[0]
    points = [
        (timestamp, value)
        for timestamp, value in zip(
            result.get("Timestamps", []), result.get("Values", [])
        )
        if isinstance(timestamp, datetime)
        and start <= timestamp <= end
        and isinstance(value, (int, float))
        and math.isfinite(value)
    ]
    points = sorted(points)[:limit]
    metric = (alarm.get("Metrics") or [{}])[0].get("MetricStat", {}).get("Metric") or {
        "Namespace": alarm.get("Namespace"),
        "MetricName": alarm.get("MetricName"),
        "Dimensions": alarm.get("Dimensions", []),
    }
    content = {
        "namespace": metric.get("Namespace"),
        "metric_name": metric.get("MetricName"),
        "dimensions": redact_value(metric.get("Dimensions", [])),
        "statistic": alarm.get("Statistic")
        or (alarm.get("Metrics") or [{}])[0].get("MetricStat", {}).get("Stat"),
        "period": alarm.get("Period")
        or (alarm.get("Metrics") or [{}])[0].get("MetricStat", {}).get("Period"),
        "threshold": alarm.get("Threshold"),
        "comparison_operator": alarm.get("ComparisonOperator"),
        "unit": result.get("Label") or alarm.get("Unit"),
        "region": receipt.region,
        "points": [
            {"timestamp": timestamp.isoformat(), "value": value}
            for timestamp, value in points
        ],
    }
    return [
        (
            ContextItemType.METRIC,
            receipt.alarm_identity,
            receipt.observed_at,
            content,
            len(result.get("Values", [])) > limit,
        )
    ]


def _bound_items(snapshot_id, binding, values, max_chars):
    items = []
    used = 0
    truncated = False
    for kind, source, observed, content, item_truncated in values:
        safe = redact_value(content)
        encoded = json.dumps(
            safe, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        if used + len(encoded) > max_chars:
            truncated = True
            break
        used += len(encoded)
        items.append(
            IncidentContextItem(
                id=IncidentContextItemId.new(),
                snapshot_id=snapshot_id,
                scope=binding.run.scope,
                type=kind,
                source=source,
                observed_at=observed,
                content=safe,
                sequence=len(items),
                truncated=item_truncated,
            )
        )
    return tuple(items), truncated


def _capability_verified(integration, capability, region):
    return integration.verification is not None and any(
        check.capability is capability and check.region == region and check.passed
        for check in integration.verification.checks
    )


def _diagnostic(collector, exc):
    return CollectorDiagnostic(
        collector, CollectorStatus.FAILED, exc.code.value, exc.summary
    )


def _budget_diagnostic(collector):
    return CollectorDiagnostic(
        collector,
        CollectorStatus.FAILED,
        "provider_call_budget_exhausted",
        "Context provider call budget was exhausted",
    )


def _provider_failure(exc, code):
    retryable = exc.code in {
        AwsVerificationError.THROTTLED,
        AwsVerificationError.NETWORK_ERROR,
    }
    category = (
        JobErrorCategory.TRANSIENT if retryable else JobErrorCategory.AUTHORIZATION
    )
    return ContextEnrichmentFailure(code, category, retryable, exc.summary)


def _identity_matches_role(identity_arn: str, role_arn: str) -> bool:
    match = re.fullmatch(r"arn:aws:iam::(\d{12}):role/(.+)", role_arn)
    if match is None:
        return False
    account, role_path = match.groups()
    role_name = role_path.rsplit("/", 1)[-1]
    return bool(
        re.fullmatch(
            rf"arn:aws:sts::{account}:assumed-role/{re.escape(role_name)}/.+",
            identity_arn,
        )
    )


def _append(existing: str, context: str) -> str:
    return f"{existing.rstrip()}\n\nCloudWatch incident context (redacted):\n{context}".strip()
