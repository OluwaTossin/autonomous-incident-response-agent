"""Normalized CloudWatch alarm delivery contracts without transport dependencies."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from app.domain.common import (
    ActorReference,
    DomainInvariantError,
    WorkspaceScope,
    require_aware,
)
from app.domain.identifiers import (
    AlertReceiptId,
    AwsAlarmStateId,
    IncidentId,
    IntegrationId,
    TriageRunId,
)

_ACCOUNT_RE = re.compile(r"^[0-9]{12}$")
_REGION_RE = re.compile(r"^[a-z]{2}(?:-gov)?-[a-z0-9-]+-[0-9]+$")
_EVENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_ALARM_ARN_RE = re.compile(
    r"^arn:aws:cloudwatch:(?P<region>[a-z0-9-]+):(?P<account>[0-9]{12}):alarm:(?P<name>.{1,255})$"
)


class CloudWatchAlarmValue(StrEnum):
    ALARM = "ALARM"
    OK = "OK"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class AlertReceiptStatus(StrEnum):
    ACCEPTED = "accepted"
    IGNORED_STALE = "ignored_stale"
    IGNORED_POLICY = "ignored_policy"


@dataclass(frozen=True, slots=True)
class CloudWatchAlarmEvent:
    schema_version: int
    event_id: str
    account_id: str
    region: str
    observed_at: datetime
    alarm_name: str
    alarm_arn: str
    state: CloudWatchAlarmValue
    previous_state: CloudWatchAlarmValue
    reason: str
    resources: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise DomainInvariantError("Unsupported alarm event schema version")
        if not _EVENT_ID_RE.fullmatch(self.event_id):
            raise DomainInvariantError("EventBridge event id is invalid")
        if not _ACCOUNT_RE.fullmatch(self.account_id):
            raise DomainInvariantError("EventBridge account is invalid")
        if not _REGION_RE.fullmatch(self.region):
            raise DomainInvariantError("EventBridge region is invalid")
        require_aware(self.observed_at, "observed_at")
        name = self.alarm_name.strip()
        reason = self.reason.strip()
        if not name or len(name) > 255:
            raise DomainInvariantError("CloudWatch alarm name is invalid")
        if not reason or len(reason) > 2000:
            raise DomainInvariantError("CloudWatch alarm reason is invalid")
        if not 1 <= len(self.resources) <= 20:
            raise DomainInvariantError("EventBridge resources must contain 1 to 20 values")
        if any(not value or len(value) > 1000 for value in self.resources):
            raise DomainInvariantError("EventBridge resource is invalid")
        arn = _ALARM_ARN_RE.fullmatch(self.alarm_arn)
        if (
            arn is None
            or arn.group("account") != self.account_id
            or arn.group("region") != self.region
            or arn.group("name") != name
            or self.alarm_arn not in self.resources
        ):
            raise DomainInvariantError(
                "CloudWatch alarm ARN must match the event account, region, and name"
            )
        if self.state is self.previous_state:
            raise DomainInvariantError("CloudWatch alarm event must describe a state change")
        object.__setattr__(self, "alarm_name", name)
        object.__setattr__(self, "reason", reason)

    @property
    def alarm_identity(self) -> str:
        return self.alarm_arn

    @property
    def alarm_identity_hash(self) -> str:
        return hashlib.sha256(self.alarm_identity.encode("utf-8")).hexdigest()

    @property
    def payload_hash(self) -> str:
        canonical = {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "account_id": self.account_id,
            "region": self.region,
            "observed_at": self.observed_at.isoformat(),
            "alarm_name": self.alarm_name,
            "alarm_arn": self.alarm_arn,
            "state": self.state.value,
            "previous_state": self.previous_state.value,
            "reason": self.reason,
            "resources": sorted(self.resources),
        }
        encoded = json.dumps(
            canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class AlertEventReceipt:
    id: AlertReceiptId
    scope: WorkspaceScope
    integration_id: IntegrationId
    event_id: str
    payload_hash: str
    alarm_identity: str
    alarm_identity_hash: str
    alarm_name: str
    account_id: str
    region: str
    state: CloudWatchAlarmValue
    previous_state: CloudWatchAlarmValue
    observed_at: datetime
    received_at: datetime
    status: AlertReceiptStatus
    created_by: ActorReference
    incident_id: IncidentId | None = None
    triage_run_id: TriageRunId | None = None

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "observed_at")
        require_aware(self.received_at, "received_at")
        if not _EVENT_ID_RE.fullmatch(self.event_id):
            raise DomainInvariantError("Event receipt id is invalid")
        for name, value in (
            ("payload_hash", self.payload_hash),
            ("alarm_identity_hash", self.alarm_identity_hash),
        ):
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                raise DomainInvariantError(f"{name} is invalid")

    def processed(
        self,
        status: AlertReceiptStatus,
        *,
        incident_id: IncidentId | None = None,
        triage_run_id: TriageRunId | None = None,
    ) -> AlertEventReceipt:
        return replace(
            self,
            status=status,
            incident_id=incident_id,
            triage_run_id=triage_run_id,
        )


@dataclass(frozen=True, slots=True)
class AwsAlarmCurrentState:
    id: AwsAlarmStateId
    scope: WorkspaceScope
    integration_id: IntegrationId
    alarm_identity: str
    alarm_identity_hash: str
    alarm_name: str
    latest_event_id: str
    latest_state: CloudWatchAlarmValue
    latest_observed_at: datetime
    updated_at: datetime
    incident_id: IncidentId | None = None

    def __post_init__(self) -> None:
        require_aware(self.latest_observed_at, "latest_observed_at")
        require_aware(self.updated_at, "updated_at")

    def advance(
        self,
        event: CloudWatchAlarmEvent,
        *,
        at: datetime,
        incident_id: IncidentId | None,
    ) -> AwsAlarmCurrentState:
        return replace(
            self,
            alarm_name=event.alarm_name,
            latest_event_id=event.event_id,
            latest_state=event.state,
            latest_observed_at=event.observed_at,
            updated_at=at,
            incident_id=incident_id,
        )
