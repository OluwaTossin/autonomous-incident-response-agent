"""Versioned hosted incident and asynchronous triage HTTP routes."""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.application.incidents import (
    HostedIncidentConflict,
    HostedIncidentInput,
    HostedIncidentNotFound,
    HostedIncidentService,
    HostedTriageConflict,
    HostedTriageNotFound,
    IncidentListCursor,
    TriageRunListCursor,
    TriageView,
)
from app.auth.context import ActorContext
from app.authorization.service import AuthorizationDenied
from app.domain.identifiers import IncidentId, OrganizationId, TriageRunId, WorkspaceId
from app.domain.incidents import Incident, IncidentState, TriageRun, TriageRunState
from app.models.triage import TriageOutput


class HostedErrorDetail(BaseModel):
    code: str
    message: str


class HostedErrorResponse(BaseModel):
    detail: HostedErrorDetail | str


class IncidentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=4000)
    service_name: str = Field(min_length=1, max_length=200)
    environment: str = Field(min_length=1, max_length=80)
    source_provider: str = Field(min_length=1, max_length=80)
    source_type: str = Field(min_length=1, max_length=80)
    observed_at: datetime
    external_event_id: str | None = Field(default=None, min_length=1, max_length=255)
    source_url: str | None = Field(default=None, max_length=1000)
    severity_hint: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] | None = None
    metric_summary: str = Field(default="", max_length=2000)


class IncidentResponse(BaseModel):
    incident_id: str
    workspace_id: str
    state: str
    title: str
    service_name: str
    environment: str
    source_provider: str
    source_type: str
    external_event_id: str | None
    observed_at: datetime
    created_at: datetime
    updated_at: datetime


class IncidentPageResponse(BaseModel):
    items: list[IncidentResponse]
    next_cursor: str | None = None


class IncidentStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: Literal["investigating", "resolved", "closed"]


class TriageRequestResponse(BaseModel):
    triage_run_id: str
    triage_id: str
    incident_id: str
    job_id: str
    state: str
    job_state: str
    created_at: datetime


class HostedTriageResult(TriageOutput):
    triage_id: str


class EvidenceResponse(BaseModel):
    sequence: int
    type: str
    source: str
    reason: str
    origin: str | None
    document_id: str | None
    document_version_id: str | None
    knowledge_index_version_id: str | None
    chunk_index: int | None
    score: float | None


class TriageRunResponse(BaseModel):
    triage_run_id: str
    triage_id: str
    incident_id: str
    job_id: str
    state: str
    job_state: str
    cancellation_requested: bool
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    failure_code: str | None
    failure_category: str | None
    failure_summary: str | None
    result: HostedTriageResult | None
    evidence: list[EvidenceResponse]


class TriageRunListItem(BaseModel):
    triage_run_id: str
    triage_id: str
    incident_id: str
    state: str
    created_at: datetime
    completed_at: datetime | None


class TriageRunPageResponse(BaseModel):
    items: list[TriageRunListItem]
    next_cursor: str | None = None


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diagnosis_correct: bool | None = None
    actions_useful: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)


class FeedbackResponse(BaseModel):
    feedback_id: str
    triage_run_id: str
    created_at: datetime


def build_hosted_incident_router(
    service: HostedIncidentService,
    actor_dependency,
) -> APIRouter:
    router = APIRouter(
        prefix="/v3/organizations/{organization_id}/workspaces/{workspace_id}",
        tags=["hosted-incidents"],
        responses={
            401: {"model": HostedErrorResponse},
            403: {"model": HostedErrorResponse},
            404: {"model": HostedErrorResponse},
            409: {"model": HostedErrorResponse},
        },
    )

    @router.post(
        "/incidents",
        response_model=IncidentResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_incident(
        organization_id: str,
        workspace_id: str,
        body: IncidentCreateRequest,
        actor: ActorContext = Depends(actor_dependency),
    ) -> IncidentResponse:
        try:
            incident = service.create_incident(
                actor,
                OrganizationId(organization_id),
                WorkspaceId(workspace_id),
                HostedIncidentInput(**body.model_dump()),
            )
            return _incident_response(incident)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get("/incidents", response_model=IncidentPageResponse)
    def list_incidents(
        organization_id: str,
        workspace_id: str,
        actor: ActorContext = Depends(actor_dependency),
        limit: int = Query(50, ge=1, le=100),
        cursor: str | None = None,
        incident_state: IncidentState | None = Query(None, alias="state"),
    ) -> IncidentPageResponse:
        try:
            before = _decode_incident_cursor(cursor) if cursor else None
            items = service.list_incidents(
                actor,
                OrganizationId(organization_id),
                WorkspaceId(workspace_id),
                limit=limit + 1,
                before=before,
                state=incident_state,
            )
            page = items[:limit]
            next_cursor = (
                _encode_cursor(page[-1].created_at, page[-1].id)
                if len(items) > limit
                else None
            )
            return IncidentPageResponse(
                items=[_incident_response(item) for item in page],
                next_cursor=next_cursor,
            )
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get("/incidents/{incident_id}", response_model=IncidentResponse)
    def get_incident(
        organization_id: str,
        workspace_id: str,
        incident_id: str,
        actor: ActorContext = Depends(actor_dependency),
    ) -> IncidentResponse:
        try:
            incident = service.get_incident(
                actor,
                OrganizationId(organization_id),
                WorkspaceId(workspace_id),
                IncidentId(incident_id),
            )
            return _incident_response(incident)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.patch("/incidents/{incident_id}/state", response_model=IncidentResponse)
    def transition_incident(
        organization_id: str,
        workspace_id: str,
        incident_id: str,
        body: IncidentStateRequest,
        actor: ActorContext = Depends(actor_dependency),
    ) -> IncidentResponse:
        try:
            incident = service.transition_incident(
                actor,
                OrganizationId(organization_id),
                WorkspaceId(workspace_id),
                IncidentId(incident_id),
                IncidentState(body.state),
            )
            return _incident_response(incident)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post(
        "/incidents/{incident_id}/triage",
        response_model=TriageRequestResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def request_triage(
        organization_id: str,
        workspace_id: str,
        incident_id: str,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        actor: ActorContext = Depends(actor_dependency),
    ) -> TriageRequestResponse:
        try:
            requested = service.request_triage(
                actor,
                OrganizationId(organization_id),
                WorkspaceId(workspace_id),
                IncidentId(incident_id),
                idempotency_key=idempotency_key,
            )
            return _triage_request_response(requested.run, requested.job)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get("/triage-runs", response_model=TriageRunPageResponse)
    def list_triage_runs(
        organization_id: str,
        workspace_id: str,
        actor: ActorContext = Depends(actor_dependency),
        limit: int = Query(50, ge=1, le=100),
        cursor: str | None = None,
        incident_id: str | None = None,
        triage_state: TriageRunState | None = Query(None, alias="state"),
    ) -> TriageRunPageResponse:
        try:
            before = _decode_triage_cursor(cursor) if cursor else None
            runs = service.list_triage_runs(
                actor,
                OrganizationId(organization_id),
                WorkspaceId(workspace_id),
                limit=limit + 1,
                before=before,
                incident_id=IncidentId(incident_id) if incident_id else None,
                state=triage_state,
            )
            page = runs[:limit]
            next_cursor = (
                _encode_cursor(page[-1].created_at, page[-1].id)
                if len(runs) > limit
                else None
            )
            return TriageRunPageResponse(
                items=[_triage_list_item(run) for run in page],
                next_cursor=next_cursor,
            )
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get("/triage-runs/{triage_run_id}", response_model=TriageRunResponse)
    def get_triage_run(
        organization_id: str,
        workspace_id: str,
        triage_run_id: str,
        actor: ActorContext = Depends(actor_dependency),
    ) -> TriageRunResponse:
        try:
            view = service.get_triage(
                actor,
                OrganizationId(organization_id),
                WorkspaceId(workspace_id),
                TriageRunId(triage_run_id),
            )
            return _triage_response(view)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get(
        "/triage-runs/{triage_run_id}/result",
        response_model=HostedTriageResult,
    )
    def get_triage_result(
        organization_id: str,
        workspace_id: str,
        triage_run_id: str,
        actor: ActorContext = Depends(actor_dependency),
    ) -> HostedTriageResult:
        try:
            view = service.get_triage(
                actor,
                OrganizationId(organization_id),
                WorkspaceId(workspace_id),
                TriageRunId(triage_run_id),
            )
            response = _triage_response(view)
            if response.result is None:
                raise HostedTriageConflict("Triage result is not available")
            return response.result
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get(
        "/triage-runs/{triage_run_id}/evidence",
        response_model=list[EvidenceResponse],
    )
    def get_triage_evidence(
        organization_id: str,
        workspace_id: str,
        triage_run_id: str,
        actor: ActorContext = Depends(actor_dependency),
    ) -> list[EvidenceResponse]:
        try:
            view = service.get_triage(
                actor,
                OrganizationId(organization_id),
                WorkspaceId(workspace_id),
                TriageRunId(triage_run_id),
            )
            return _triage_response(view).evidence
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post(
        "/triage-runs/{triage_run_id}/cancel",
        response_model=TriageRunResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def cancel_triage_run(
        organization_id: str,
        workspace_id: str,
        triage_run_id: str,
        actor: ActorContext = Depends(actor_dependency),
    ) -> TriageRunResponse:
        try:
            view = service.cancel_triage(
                actor,
                OrganizationId(organization_id),
                WorkspaceId(workspace_id),
                TriageRunId(triage_run_id),
            )
            return _triage_response(view)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post(
        "/triage-runs/{triage_run_id}/feedback",
        response_model=FeedbackResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_feedback(
        organization_id: str,
        workspace_id: str,
        triage_run_id: str,
        body: FeedbackRequest,
        actor: ActorContext = Depends(actor_dependency),
    ) -> FeedbackResponse:
        try:
            feedback = service.submit_feedback(
                actor,
                OrganizationId(organization_id),
                WorkspaceId(workspace_id),
                TriageRunId(triage_run_id),
                **body.model_dump(),
            )
            return FeedbackResponse(
                feedback_id=str(feedback.id),
                triage_run_id=str(feedback.triage_run.id),
                created_at=feedback.created_at,
            )
        except Exception as exc:
            raise _http_error(exc) from exc

    return router


def _incident_response(incident: Incident) -> IncidentResponse:
    payload = incident.payload
    return IncidentResponse(
        incident_id=str(incident.id),
        workspace_id=str(incident.scope.workspace_id),
        state=incident.state.value,
        title=payload.alert_title,
        service_name=payload.service_name,
        environment=payload.environment,
        source_provider=incident.source.provider,
        source_type=incident.source.source_type,
        external_event_id=incident.source.external_id,
        observed_at=datetime.fromisoformat(payload.time_of_occurrence.replace("Z", "+00:00")),
        created_at=incident.created_at,
        updated_at=incident.updated_at,
    )


def _triage_request_response(run: TriageRun, job) -> TriageRequestResponse:
    return TriageRequestResponse(
        triage_run_id=str(run.id),
        triage_id=run.legacy_triage_id,
        incident_id=str(run.incident.id),
        job_id=str(job.id),
        state=run.state.value,
        job_state=job.state.value,
        created_at=run.created_at,
    )


def _triage_response(view: TriageView) -> TriageRunResponse:
    run = view.run
    result = (
        HostedTriageResult(
            **run.result.model_dump(mode="python"), triage_id=run.legacy_triage_id
        )
        if run.result is not None
        else None
    )
    return TriageRunResponse(
        triage_run_id=str(run.id),
        triage_id=run.legacy_triage_id,
        incident_id=str(run.incident.id),
        job_id=str(view.job.id),
        state=run.state.value,
        job_state=view.job.state.value,
        cancellation_requested=view.job.cancellation_requested_at is not None,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        failure_code=run.error_code,
        failure_category=run.error_category,
        failure_summary=run.error_message,
        result=result,
        evidence=[
            EvidenceResponse(
                sequence=item.sequence,
                type=item.type,
                source=item.source,
                reason=item.reason,
                origin=item.origin,
                document_id=item.document_id,
                document_version_id=item.document_version_id,
                knowledge_index_version_id=item.knowledge_index_version_id,
                chunk_index=item.chunk_index,
                score=item.score,
            )
            for item in view.evidence
        ],
    )


def _triage_list_item(run: TriageRun) -> TriageRunListItem:
    return TriageRunListItem(
        triage_run_id=str(run.id),
        triage_id=run.legacy_triage_id,
        incident_id=str(run.incident.id),
        state=run.state.value,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )


def _encode_cursor(created_at: datetime, identifier) -> str:
    payload = json.dumps(
        {"created_at": created_at.isoformat(), "id": str(identifier)},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> tuple[datetime, str]:
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        return datetime.fromisoformat(raw["created_at"]), str(raw["id"])
    except Exception as exc:
        raise ValueError("Invalid pagination cursor") from exc


def _decode_incident_cursor(value: str) -> IncidentListCursor:
    created_at, identifier = _decode_cursor(value)
    return IncidentListCursor(created_at, IncidentId(identifier))


def _decode_triage_cursor(value: str) -> TriageRunListCursor:
    created_at, identifier = _decode_cursor(value)
    return TriageRunListCursor(created_at, TriageRunId(identifier))


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AuthorizationDenied):
        return HTTPException(403, detail={"code": "forbidden", "message": "Access denied"})
    if isinstance(exc, (HostedIncidentNotFound, HostedTriageNotFound)):
        return HTTPException(404, detail={"code": "not_found", "message": str(exc)})
    if isinstance(exc, (HostedIncidentConflict, HostedTriageConflict)):
        return HTTPException(409, detail={"code": "conflict", "message": str(exc)})
    if isinstance(exc, (ValueError, TypeError)):
        return HTTPException(422, detail={"code": "invalid_request", "message": str(exc)})
    return HTTPException(
        500,
        detail={"code": "internal_error", "message": "Request could not be completed"},
    )
