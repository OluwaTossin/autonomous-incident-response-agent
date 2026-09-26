"""Versioned hosted incident and asynchronous triage HTTP routes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.application.incidents import (
    HostedIncidentConflict,
    HostedIncidentInput,
    HostedIncidentNotFound,
    HostedIncidentService,
    HostedTriageConflict,
    HostedTriageNotFound,
    IncidentHistoryItem,
    IncidentListCursor,
    TriageRunListCursor,
    TriageHistoryItem,
    TriageView,
)
from app.application.actions import (
    ActionProposalNotFound,
    HostedActionProposalService,
)
from app.application.approvals import (
    ApprovalConflict,
    ApprovalEligibilityError,
    ApprovalNotFound,
    HostedApprovalService,
)
from app.application.execution_intents import (
    ExecutionIntentConflict,
    ExecutionIntentNotFound,
    ExecutionIntentValidationError,
    HostedExecutionIntentService,
)
from app.auth.context import ActorContext
from app.authorization.service import AuthorizationDenied
from app.domain.identifiers import (
    ActionId,
    ApprovalId,
    ExecutionIntentId,
    IncidentId,
    OrganizationId,
    TriageRunId,
    WorkspaceId,
)
from app.domain.incidents import Incident, IncidentState, TriageRun, TriageRunState
from app.domain.actions import ActionProposal, Approval, action_parameters_to_dict
from app.domain.execution import ExecutionIntent
from app.models.triage import TriageOutput
from app.security.cursors import CursorCodec, InvalidCursor


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
    source_url: str | None
    description: str
    metric_summary: str
    severity_hint: str | None
    observed_at: datetime
    created_at: datetime
    updated_at: datetime


class IncidentListItem(IncidentResponse):
    latest_triage_run_id: str | None
    latest_triage_state: str | None
    latest_severity: str | None
    latest_confidence: float | None
    latest_escalate: bool | None
    triage_run_count: int


class IncidentPageResponse(BaseModel):
    items: list[IncidentListItem]
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


class ContextDiagnosticResponse(BaseModel):
    collector: str
    status: str
    code: str | None
    summary: str | None


class ContextItemResponse(BaseModel):
    sequence: int
    type: str
    source: str
    observed_at: datetime
    content: dict[str, Any]
    truncated: bool


class IncidentContextResponse(BaseModel):
    snapshot_id: str
    integration_id: str
    provider: str
    region: str
    status: str
    window_start: datetime
    window_end: datetime
    collected_at: datetime
    policy_version: str
    truncated: bool
    diagnostics: list[ContextDiagnosticResponse]
    items: list[ContextItemResponse]


class TriageRunResponse(BaseModel):
    triage_run_id: str
    triage_id: str
    incident_id: str
    job_id: str
    state: str
    job_state: str
    cancellation_requested: bool
    attempt_count: int
    max_attempts: int
    next_attempt_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    failure_code: str | None
    failure_category: str | None
    failure_summary: str | None
    result: HostedTriageResult | None
    evidence: list[EvidenceResponse]
    operational_context: IncidentContextResponse | None


class TriageRunListItem(BaseModel):
    triage_run_id: str
    triage_id: str
    incident_id: str
    state: str
    job_state: str
    attempt_count: int
    max_attempts: int
    next_attempt_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    failure_category: str | None
    failure_summary: str | None
    severity: str | None
    confidence: float | None
    escalate: bool | None


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


class ActionTargetResponse(BaseModel):
    type: str
    identifier: str
    provider: str
    provenance: str
    integration_id: str | None
    account_id: str | None
    region: str | None


class ActionProposalResponse(BaseModel):
    action_proposal_id: str
    incident_id: str
    triage_run_id: str
    proposal_type: str
    target: ActionTargetResponse
    summary: str
    rationale: str
    parameters: dict[str, Any]
    risk_level: str
    reversibility: str
    policy_status: str
    policy_reason: str
    lifecycle_state: str
    source_result_version: int
    source_result_hash: str
    proposal_schema_version: int
    created_by_type: str
    created_at: datetime


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=1000)


class ApprovalRejectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)


class ApprovalResponse(BaseModel):
    approval_id: str
    action_proposal_id: str
    state: str
    state_version: int
    proposal_schema_version: int
    source_result_version: int
    source_result_hash: str
    normalized_action_hash: str
    requested_by_type: str
    requested_by_id: str | None
    requested_at: datetime
    expires_at: datetime
    decided_by_type: str | None
    decided_by_id: str | None
    decided_at: datetime | None
    decision_reason: str | None
    created_at: datetime
    updated_at: datetime


class ExecutionIntentCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


class ExecutionIntentPrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExecutionIntentResponse(BaseModel):
    execution_intent_id: str
    action_proposal_id: str
    approval_id: str
    incident_id: str
    triage_run_id: str
    lifecycle_state: str
    connector_kind: str
    operation_kind: str
    provider: str
    target: ActionTargetResponse
    parameters: dict[str, Any]
    request_schema_version: int
    proposal_schema_version: int
    source_result_version: int
    source_result_hash: str
    normalized_action_hash: str
    approval_state_version: int
    approval_binding_hash: str
    intent_hash: str
    risk_level: str
    reversibility: str
    policy_version: int
    approved_by_type: str
    approved_by_id: str
    approved_at: datetime
    created_by_type: str
    created_at: datetime
    updated_at: datetime
    execute_before: datetime
    terminal_at: datetime | None
    terminal_reason: str | None
    validation_status: Literal["passed"] = "passed"
    execution_status: Literal["not_executed"] = "not_executed"


def build_hosted_incident_router(
    service: HostedIncidentService,
    actor_dependency,
    *,
    cursor_codec: CursorCodec,
    action_proposals: HostedActionProposalService | None = None,
    approvals: HostedApprovalService | None = None,
    execution_intents: HostedExecutionIntentService | None = None,
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
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> IncidentPageResponse:
        try:
            organization = OrganizationId(organization_id)
            workspace = WorkspaceId(workspace_id)
            before = (
                _decode_incident_cursor(
                    cursor_codec, cursor, organization, workspace
                )
                if cursor
                else None
            )
            items = service.list_incident_history(
                actor,
                organization,
                workspace,
                limit=limit + 1,
                before=before,
                state=incident_state,
                created_from=created_from,
                created_to=created_to,
            )
            page = items[:limit]
            next_cursor = (
                _encode_cursor(
                    cursor_codec,
                    "incidents",
                    organization,
                    workspace,
                    page[-1].incident.created_at,
                    page[-1].incident.id,
                )
                if len(items) > limit
                else None
            )
            return IncidentPageResponse(
                items=[_incident_list_item(item) for item in page],
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
            organization = OrganizationId(organization_id)
            workspace = WorkspaceId(workspace_id)
            before = (
                _decode_triage_cursor(
                    cursor_codec, cursor, organization, workspace
                )
                if cursor
                else None
            )
            runs = service.list_triage_history(
                actor,
                organization,
                workspace,
                limit=limit + 1,
                before=before,
                incident_id=IncidentId(incident_id) if incident_id else None,
                state=triage_state,
            )
            page = runs[:limit]
            next_cursor = (
                _encode_cursor(
                    cursor_codec,
                    "triage-runs",
                    organization,
                    workspace,
                    page[-1].run.created_at,
                    page[-1].run.id,
                )
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

    if action_proposals is not None:

        @router.get(
            "/incidents/{incident_id}/action-proposals",
            response_model=list[ActionProposalResponse],
        )
        def list_incident_action_proposals(
            organization_id: str,
            workspace_id: str,
            incident_id: str,
            actor: ActorContext = Depends(actor_dependency),
        ) -> list[ActionProposalResponse]:
            try:
                proposals = action_proposals.list_for_incident(
                    actor,
                    OrganizationId(organization_id),
                    WorkspaceId(workspace_id),
                    IncidentId(incident_id),
                )
                return [_action_proposal_response(item) for item in proposals]
            except Exception as exc:
                raise _http_error(exc) from exc

        @router.get(
            "/triage-runs/{triage_run_id}/action-proposals",
            response_model=list[ActionProposalResponse],
        )
        def list_triage_action_proposals(
            organization_id: str,
            workspace_id: str,
            triage_run_id: str,
            actor: ActorContext = Depends(actor_dependency),
        ) -> list[ActionProposalResponse]:
            try:
                proposals = action_proposals.list_for_triage_run(
                    actor,
                    OrganizationId(organization_id),
                    WorkspaceId(workspace_id),
                    TriageRunId(triage_run_id),
                )
                return [_action_proposal_response(item) for item in proposals]
            except Exception as exc:
                raise _http_error(exc) from exc

        @router.get(
            "/action-proposals/{proposal_id}",
            response_model=ActionProposalResponse,
        )
        def get_action_proposal(
            organization_id: str,
            workspace_id: str,
            proposal_id: str,
            actor: ActorContext = Depends(actor_dependency),
        ) -> ActionProposalResponse:
            try:
                proposal = action_proposals.get(
                    actor,
                    OrganizationId(organization_id),
                    WorkspaceId(workspace_id),
                    ActionId(proposal_id),
                )
                return _action_proposal_response(proposal)
            except Exception as exc:
                raise _http_error(exc) from exc

    if approvals is not None:

        @router.post(
            "/action-proposals/{proposal_id}/approval",
            response_model=ApprovalResponse,
        )
        def request_action_approval(
            organization_id: str,
            workspace_id: str,
            proposal_id: str,
            actor: ActorContext = Depends(actor_dependency),
        ) -> ApprovalResponse:
            try:
                approval = approvals.request_approval(
                    actor,
                    OrganizationId(organization_id),
                    WorkspaceId(workspace_id),
                    ActionId(proposal_id),
                )
                return _approval_response(approval)
            except Exception as exc:
                raise _http_error(exc) from exc

        @router.get(
            "/action-proposals/{proposal_id}/approvals",
            response_model=list[ApprovalResponse],
        )
        def list_action_approvals(
            organization_id: str,
            workspace_id: str,
            proposal_id: str,
            actor: ActorContext = Depends(actor_dependency),
        ) -> list[ApprovalResponse]:
            try:
                items = approvals.list_for_proposal(
                    actor,
                    OrganizationId(organization_id),
                    WorkspaceId(workspace_id),
                    ActionId(proposal_id),
                )
                return [_approval_response(item) for item in items]
            except Exception as exc:
                raise _http_error(exc) from exc

        @router.get("/approvals/{approval_id}", response_model=ApprovalResponse)
        def get_approval(
            organization_id: str,
            workspace_id: str,
            approval_id: str,
            actor: ActorContext = Depends(actor_dependency),
        ) -> ApprovalResponse:
            try:
                approval = approvals.get_approval(
                    actor,
                    OrganizationId(organization_id),
                    WorkspaceId(workspace_id),
                    ApprovalId(approval_id),
                )
                return _approval_response(approval)
            except Exception as exc:
                raise _http_error(exc) from exc

        @router.post(
            "/approvals/{approval_id}/approve", response_model=ApprovalResponse
        )
        def approve_action(
            organization_id: str,
            workspace_id: str,
            approval_id: str,
            body: ApprovalDecisionRequest,
            actor: ActorContext = Depends(actor_dependency),
        ) -> ApprovalResponse:
            try:
                approval = approvals.approve(
                    actor,
                    OrganizationId(organization_id),
                    WorkspaceId(workspace_id),
                    ApprovalId(approval_id),
                    reason=body.reason,
                )
                return _approval_response(approval)
            except Exception as exc:
                raise _http_error(exc) from exc

        @router.post("/approvals/{approval_id}/reject", response_model=ApprovalResponse)
        def reject_action(
            organization_id: str,
            workspace_id: str,
            approval_id: str,
            body: ApprovalRejectionRequest,
            actor: ActorContext = Depends(actor_dependency),
        ) -> ApprovalResponse:
            try:
                approval = approvals.reject(
                    actor,
                    OrganizationId(organization_id),
                    WorkspaceId(workspace_id),
                    ApprovalId(approval_id),
                    reason=body.reason,
                )
                return _approval_response(approval)
            except Exception as exc:
                raise _http_error(exc) from exc

        @router.post("/approvals/{approval_id}/cancel", response_model=ApprovalResponse)
        def cancel_approval(
            organization_id: str,
            workspace_id: str,
            approval_id: str,
            body: ApprovalDecisionRequest,
            actor: ActorContext = Depends(actor_dependency),
        ) -> ApprovalResponse:
            try:
                approval = approvals.cancel(
                    actor,
                    OrganizationId(organization_id),
                    WorkspaceId(workspace_id),
                    ApprovalId(approval_id),
                    reason=body.reason,
                )
                return _approval_response(approval)
            except Exception as exc:
                raise _http_error(exc) from exc

    if execution_intents is not None:

        @router.post(
            "/approvals/{approval_id}/execution-intent",
            response_model=ExecutionIntentResponse,
        )
        def prepare_execution_intent(
            organization_id: str,
            workspace_id: str,
            approval_id: str,
            body: ExecutionIntentPrepareRequest = Body(
                default_factory=ExecutionIntentPrepareRequest
            ),
            actor: ActorContext = Depends(actor_dependency),
        ) -> ExecutionIntentResponse:
            try:
                intent = execution_intents.prepare(
                    actor,
                    OrganizationId(organization_id),
                    WorkspaceId(workspace_id),
                    ApprovalId(approval_id),
                )
                return _execution_intent_response(intent)
            except Exception as exc:
                raise _http_error(exc) from exc

        @router.get(
            "/execution-intents/{intent_id}",
            response_model=ExecutionIntentResponse,
        )
        def get_execution_intent(
            organization_id: str,
            workspace_id: str,
            intent_id: str,
            actor: ActorContext = Depends(actor_dependency),
        ) -> ExecutionIntentResponse:
            try:
                intent = execution_intents.get(
                    actor,
                    OrganizationId(organization_id),
                    WorkspaceId(workspace_id),
                    ExecutionIntentId(intent_id),
                )
                return _execution_intent_response(intent)
            except Exception as exc:
                raise _http_error(exc) from exc

        @router.get(
            "/action-proposals/{proposal_id}/execution-intents",
            response_model=list[ExecutionIntentResponse],
        )
        def list_execution_intents(
            organization_id: str,
            workspace_id: str,
            proposal_id: str,
            actor: ActorContext = Depends(actor_dependency),
        ) -> list[ExecutionIntentResponse]:
            try:
                intents = execution_intents.list_for_proposal(
                    actor,
                    OrganizationId(organization_id),
                    WorkspaceId(workspace_id),
                    ActionId(proposal_id),
                )
                return [_execution_intent_response(intent) for intent in intents]
            except Exception as exc:
                raise _http_error(exc) from exc

        @router.post(
            "/execution-intents/{intent_id}/cancel",
            response_model=ExecutionIntentResponse,
        )
        def cancel_execution_intent(
            organization_id: str,
            workspace_id: str,
            intent_id: str,
            body: ExecutionIntentCancelRequest,
            actor: ActorContext = Depends(actor_dependency),
        ) -> ExecutionIntentResponse:
            try:
                intent = execution_intents.cancel(
                    actor,
                    OrganizationId(organization_id),
                    WorkspaceId(workspace_id),
                    ExecutionIntentId(intent_id),
                    reason=body.reason,
                )
                return _execution_intent_response(intent)
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
        source_url=incident.source.source_url,
        description=payload.logs,
        metric_summary=payload.metric_summary,
        severity_hint=getattr(payload, "severity_hint", None),
        observed_at=datetime.fromisoformat(
            payload.time_of_occurrence.replace("Z", "+00:00")
        ),
        created_at=incident.created_at,
        updated_at=incident.updated_at,
    )


def _incident_list_item(item: IncidentHistoryItem) -> IncidentListItem:
    run = item.latest_run
    result = run.result if run is not None else None
    return IncidentListItem(
        **_incident_response(item.incident).model_dump(),
        latest_triage_run_id=str(run.id) if run is not None else None,
        latest_triage_state=run.state.value if run is not None else None,
        latest_severity=result.severity if result is not None else None,
        latest_confidence=result.confidence if result is not None else None,
        latest_escalate=result.escalate if result is not None else None,
        triage_run_count=item.triage_run_count,
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
        attempt_count=view.job.attempt_count,
        max_attempts=view.job.max_attempts,
        next_attempt_at=_next_attempt_at(view.job),
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
        operational_context=(
            _context_response(view.context_snapshot)
            if view.context_snapshot is not None
            else None
        ),
    )


def _context_response(snapshot) -> IncidentContextResponse:
    return IncidentContextResponse(
        snapshot_id=str(snapshot.id),
        integration_id=str(snapshot.integration_id),
        provider=snapshot.provider,
        region=snapshot.region,
        status=snapshot.status.value,
        window_start=snapshot.window_start,
        window_end=snapshot.window_end,
        collected_at=snapshot.collected_at,
        policy_version=snapshot.policy_version,
        truncated=snapshot.truncated,
        diagnostics=[
            ContextDiagnosticResponse(
                collector=item.collector,
                status=item.status.value,
                code=item.code,
                summary=item.summary,
            )
            for item in snapshot.diagnostics
        ],
        items=[
            ContextItemResponse(
                sequence=item.sequence,
                type=item.type.value,
                source=item.source,
                observed_at=item.observed_at,
                content=item.content,
                truncated=item.truncated,
            )
            for item in snapshot.items
        ],
    )


def _action_proposal_response(proposal: ActionProposal) -> ActionProposalResponse:
    return ActionProposalResponse(
        action_proposal_id=str(proposal.id),
        incident_id=str(proposal.incident.id),
        triage_run_id=str(proposal.triage_run.id),
        proposal_type=proposal.proposal_type.value,
        target=ActionTargetResponse(
            type=proposal.target.type.value,
            identifier=proposal.target.identifier,
            provider=proposal.target.provider,
            provenance=proposal.target.provenance.value,
            integration_id=(
                str(proposal.target.integration_id)
                if proposal.target.integration_id is not None
                else None
            ),
            account_id=proposal.target.account_id,
            region=proposal.target.region,
        ),
        summary=proposal.summary,
        rationale=proposal.rationale,
        parameters=action_parameters_to_dict(proposal.parameters),
        risk_level=proposal.risk_level.value,
        reversibility=proposal.reversibility.value,
        policy_status=proposal.policy_status.value,
        policy_reason=proposal.policy_reason.value,
        lifecycle_state=proposal.lifecycle_state.value,
        source_result_version=proposal.source_result_version,
        source_result_hash=proposal.source_result_hash,
        proposal_schema_version=proposal.proposal_schema_version,
        created_by_type=proposal.created_by.kind.value,
        created_at=proposal.created_at,
    )


def _approval_response(approval: Approval) -> ApprovalResponse:
    return ApprovalResponse(
        approval_id=str(approval.id),
        action_proposal_id=str(approval.action.id),
        state=approval.state.value,
        state_version=approval.state_version,
        proposal_schema_version=approval.proposal_schema_version,
        source_result_version=approval.source_result_version,
        source_result_hash=approval.source_result_hash,
        normalized_action_hash=approval.normalized_action_hash,
        requested_by_type=approval.requested_by.kind.value,
        requested_by_id=(
            str(approval.requested_by.actor_id)
            if approval.requested_by.actor_id is not None
            else None
        ),
        requested_at=approval.requested_at,
        expires_at=approval.expires_at,
        decided_by_type=(
            approval.decided_by.kind.value if approval.decided_by is not None else None
        ),
        decided_by_id=(
            str(approval.decided_by.actor_id)
            if approval.decided_by is not None
            and approval.decided_by.actor_id is not None
            else None
        ),
        decided_at=approval.decided_at,
        decision_reason=approval.reason,
        created_at=approval.created_at,
        updated_at=approval.updated_at,
    )


def _execution_intent_response(intent: ExecutionIntent) -> ExecutionIntentResponse:
    return ExecutionIntentResponse(
        execution_intent_id=str(intent.id),
        action_proposal_id=str(intent.action.id),
        approval_id=str(intent.approval_id),
        incident_id=str(intent.incident.id),
        triage_run_id=str(intent.triage_run.id),
        lifecycle_state=intent.lifecycle_state.value,
        connector_kind=intent.connector_kind.value,
        operation_kind=intent.operation_kind.value,
        provider=intent.provider,
        target=ActionTargetResponse(
            type=intent.target.type.value,
            identifier=intent.target.identifier,
            provider=intent.target.provider,
            provenance=intent.target.provenance.value,
            integration_id=(
                str(intent.target.integration_id)
                if intent.target.integration_id is not None
                else None
            ),
            account_id=intent.target.account_id,
            region=intent.target.region,
        ),
        parameters=action_parameters_to_dict(intent.parameters),
        request_schema_version=intent.request_schema_version,
        proposal_schema_version=intent.proposal_schema_version,
        source_result_version=intent.source_result_version,
        source_result_hash=intent.source_result_hash,
        normalized_action_hash=intent.normalized_action_hash,
        approval_state_version=intent.approval_state_version,
        approval_binding_hash=intent.approval_binding_hash,
        intent_hash=intent.intent_hash,
        risk_level=intent.risk_level.value,
        reversibility=intent.reversibility.value,
        policy_version=intent.policy_version,
        approved_by_type=intent.approved_by.kind.value,
        approved_by_id=str(intent.approved_by.actor_id),
        approved_at=intent.approved_at,
        created_by_type=intent.created_by.kind.value,
        created_at=intent.created_at,
        updated_at=intent.updated_at,
        execute_before=intent.execute_before,
        terminal_at=intent.terminal_at,
        terminal_reason=intent.terminal_reason,
    )


def _triage_list_item(item: TriageHistoryItem) -> TriageRunListItem:
    run = item.run
    result = run.result
    return TriageRunListItem(
        triage_run_id=str(run.id),
        triage_id=run.legacy_triage_id,
        incident_id=str(run.incident.id),
        state=run.state.value,
        job_state=item.job.state.value,
        attempt_count=item.job.attempt_count,
        max_attempts=item.job.max_attempts,
        next_attempt_at=_next_attempt_at(item.job),
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        failure_category=run.error_category,
        failure_summary=run.error_message,
        severity=result.severity if result is not None else None,
        confidence=result.confidence if result is not None else None,
        escalate=result.escalate if result is not None else None,
    )


def _next_attempt_at(job) -> datetime | None:
    if job.state.value == "pending" and job.attempt_count > 0:
        return job.available_at
    return None


def _encode_cursor(
    codec: CursorCodec,
    kind: str,
    organization_id: OrganizationId,
    workspace_id: WorkspaceId,
    created_at: datetime,
    identifier,
) -> str:
    return codec.encode(
        kind=kind,
        scope={
            "organization_id": str(organization_id),
            "workspace_id": str(workspace_id),
        },
        values={"created_at": created_at.isoformat(), "id": str(identifier)},
    )


def _decode_cursor(
    codec: CursorCodec,
    value: str,
    kind: str,
    organization_id: OrganizationId,
    workspace_id: WorkspaceId,
) -> tuple[datetime, str]:
    try:
        raw = codec.decode(
            value,
            kind=kind,
            scope={
                "organization_id": str(organization_id),
                "workspace_id": str(workspace_id),
            },
        )
        created_at = datetime.fromisoformat(raw["created_at"])
        if created_at.tzinfo is None:
            raise ValueError
        return created_at, str(raw["id"])
    except (
        InvalidCursor,
        ValueError,
        TypeError,
        KeyError,
    ) as exc:
        raise ValueError("Invalid pagination cursor") from exc


def _decode_incident_cursor(
    codec: CursorCodec,
    value: str,
    organization_id: OrganizationId,
    workspace_id: WorkspaceId,
) -> IncidentListCursor:
    created_at, identifier = _decode_cursor(
        codec, value, "incidents", organization_id, workspace_id
    )
    return IncidentListCursor(created_at, IncidentId(identifier))


def _decode_triage_cursor(
    codec: CursorCodec,
    value: str,
    organization_id: OrganizationId,
    workspace_id: WorkspaceId,
) -> TriageRunListCursor:
    created_at, identifier = _decode_cursor(
        codec, value, "triage-runs", organization_id, workspace_id
    )
    return TriageRunListCursor(created_at, TriageRunId(identifier))


def _http_error(exc: Exception) -> HTTPException:
    from app.domain.usage import QuotaExceeded

    if isinstance(exc, QuotaExceeded):
        decision = exc.decision
        headers = (
            {"Retry-After": str(max(1, int((decision.reset_at - datetime.now(UTC)).total_seconds())))}
            if decision.reset_at is not None
            else None
        )
        return HTTPException(
            429,
            detail={
                "code": "quota_exceeded",
                "message": str(exc),
                "quota_type": decision.quota_type.value,
                "limit": decision.limit,
                "remaining": decision.remaining,
                "reset_at": decision.reset_at.isoformat() if decision.reset_at else None,
            },
            headers=headers,
        )
    if isinstance(exc, AuthorizationDenied):
        return HTTPException(
            403, detail={"code": "forbidden", "message": "Access denied"}
        )
    if isinstance(
        exc,
        (
            HostedIncidentNotFound,
            HostedTriageNotFound,
            ActionProposalNotFound,
            ApprovalNotFound,
            ExecutionIntentNotFound,
        ),
    ):
        return HTTPException(404, detail={"code": "not_found", "message": str(exc)})
    if isinstance(
        exc,
        (
            HostedIncidentConflict,
            HostedTriageConflict,
            ApprovalConflict,
            ExecutionIntentConflict,
        ),
    ):
        return HTTPException(409, detail={"code": "conflict", "message": str(exc)})
    if isinstance(exc, ExecutionIntentValidationError):
        return HTTPException(422, detail={"code": exc.code.value, "message": str(exc)})
    if isinstance(
        exc,
        (
            ValueError,
            TypeError,
            ApprovalEligibilityError,
        ),
    ):
        return HTTPException(
            422, detail={"code": "invalid_request", "message": str(exc)}
        )
    return HTTPException(
        500,
        detail={"code": "internal_error", "message": "Request could not be completed"},
    )
