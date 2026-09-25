"""Machine-facing CloudWatch Alarm EventBridge ingestion route."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.application.alert_ingestion import (
    AlertIngestionConflict,
    AlertIngestionDenied,
    AlertIngestionNotFound,
    AlertIngestionResult,
    HostedAlertIngestionService,
)
from app.auth.context import ActorContext
from app.authorization.service import AuthorizationDenied
from app.domain.alert_ingestion import CloudWatchAlarmEvent, CloudWatchAlarmValue
from app.domain.common import DomainInvariantError
from app.domain.identifiers import IntegrationId, OrganizationId, WorkspaceId

MAX_EVENT_BODY_BYTES = 65_536


class AlarmStatePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    value: Literal["ALARM", "OK", "INSUFFICIENT_DATA"]
    reason: str = Field(min_length=1, max_length=2000)


class AlarmPreviousStatePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    value: Literal["ALARM", "OK", "INSUFFICIENT_DATA"]


class AlarmDetailPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    alarm_name: str = Field(alias="alarmName", min_length=1, max_length=255)
    state: AlarmStatePayload
    previous_state: AlarmPreviousStatePayload = Field(alias="previousState")


class EventBridgeAlarmEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    version: Literal["0"]
    event_id: str = Field(alias="id", min_length=1, max_length=128)
    source: Literal["aws.cloudwatch"]
    detail_type: Literal["CloudWatch Alarm State Change"] = Field(alias="detail-type")
    account: str = Field(pattern=r"^[0-9]{12}$")
    time: datetime
    region: str = Field(pattern=r"^[a-z]{2}(?:-gov)?-[a-z0-9-]+-[0-9]+$")
    resources: list[str] = Field(min_length=1, max_length=20)
    detail: AlarmDetailPayload

    def to_domain(self) -> CloudWatchAlarmEvent:
        prefix = f"arn:aws:cloudwatch:{self.region}:{self.account}:alarm:"
        alarm_arns = [resource for resource in self.resources if resource.startswith(prefix)]
        if len(alarm_arns) != 1:
            raise DomainInvariantError(
                "EventBridge event must contain exactly one matching CloudWatch alarm ARN"
            )
        return CloudWatchAlarmEvent(
            schema_version=1,
            event_id=self.event_id,
            account_id=self.account,
            region=self.region,
            observed_at=self.time,
            alarm_name=self.detail.alarm_name,
            alarm_arn=alarm_arns[0],
            state=CloudWatchAlarmValue(self.detail.state.value),
            previous_state=CloudWatchAlarmValue(self.detail.previous_state.value),
            reason=self.detail.state.reason,
            resources=tuple(self.resources),
        )


class AlertIngestionResponse(BaseModel):
    status: str
    receipt_id: str
    incident_id: str | None
    triage_run_id: str | None


def build_hosted_alert_ingestion_router(
    service: HostedAlertIngestionService,
    machine_actor_dependency,
) -> APIRouter:
    router = APIRouter(
        prefix=(
            "/internal/v1/organizations/{organization_id}/workspaces/{workspace_id}"
            "/integrations/aws/{integration_id}"
        ),
        tags=["machine-alert-ingestion"],
    )

    @router.post(
        "/cloudwatch-alarms",
        response_model=AlertIngestionResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def ingest_cloudwatch_alarm(
        request: Request,
        organization_id: str,
        workspace_id: str,
        integration_id: str,
        actor: ActorContext = Depends(machine_actor_dependency),
    ) -> AlertIngestionResponse:
        event = await _parse_event(request)
        try:
            result = service.ingest(
                actor,
                OrganizationId(organization_id),
                WorkspaceId(workspace_id),
                IntegrationId(integration_id),
                event,
            )
            return _response(result)
        except (AuthorizationDenied, AlertIngestionDenied) as exc:
            raise HTTPException(status_code=403, detail="Forbidden") from exc
        except AlertIngestionNotFound as exc:
            raise HTTPException(status_code=404, detail="AWS integration not found") from exc
        except AlertIngestionConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (DomainInvariantError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Alarm ingestion is temporarily unavailable",
            ) from exc

    return router


async def _parse_event(request: Request) -> CloudWatchAlarmEvent:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_EVENT_BODY_BYTES:
                raise HTTPException(status_code=413, detail="Alarm event is too large")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc
    raw = await request.body()
    if len(raw) > MAX_EVENT_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Alarm event is too large")
    try:
        payload = json.loads(raw)
        envelope = EventBridgeAlarmEnvelope.model_validate(payload)
        return envelope.to_domain()
    except (json.JSONDecodeError, ValidationError, DomainInvariantError) as exc:
        raise HTTPException(status_code=422, detail="Invalid CloudWatch alarm event") from exc


def _response(result: AlertIngestionResult) -> AlertIngestionResponse:
    return AlertIngestionResponse(
        status=result.outcome.value,
        receipt_id=str(result.receipt_id),
        incident_id=str(result.incident_id) if result.incident_id else None,
        triage_run_id=str(result.triage_run_id) if result.triage_run_id else None,
    )
