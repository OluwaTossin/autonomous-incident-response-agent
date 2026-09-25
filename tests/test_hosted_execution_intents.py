"""Hosted execution-intent API exposes preparation and inspection, never execution."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.hosted_incidents import build_hosted_incident_router
from app.auth.context import ActorContext, AuthenticationMethod
from app.domain.actions import (
    AcknowledgeIncidentParameters,
    ActionPolicyReason,
    ActionPolicyStatus,
    ActionProposal,
    ActionProposalState,
    ActionProposalType,
    ActionReversibility,
    ActionRiskLevel,
    ActionTarget,
    ActionTargetProvenance,
    ActionTargetType,
    Approval,
)
from app.domain.common import ActorKind, ActorReference, WorkspaceScope
from app.domain.execution import (
    ConnectorKind,
    ExecutionIntent,
    ExecutionIntentState,
    OperationKind,
    approval_binding_hash,
)
from app.domain.identifiers import (
    ActionId,
    ApprovalId,
    ExecutionIntentId,
    IncidentId,
    OrganizationId,
    TriageRunId,
    UserId,
    WorkspaceId,
)
from app.domain.incidents import IncidentReference, TriageRunReference

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
ORG = OrganizationId("00000000-0000-4000-8000-000000000001")
WORKSPACE = WorkspaceId("00000000-0000-4000-8000-000000000002")
SCOPE = WorkspaceScope(ORG, WORKSPACE)
PROPOSAL_ID = ActionId("00000000-0000-4000-8000-000000000003")
APPROVAL_ID = ApprovalId("00000000-0000-4000-8000-000000000004")
INTENT_ID = ExecutionIntentId("00000000-0000-4000-8000-000000000005")
REQUESTER = ActorReference(
    ActorKind.HUMAN,
    actor_id=UserId("00000000-0000-4000-8000-000000000006"),
)
APPROVER = ActorReference(
    ActorKind.HUMAN,
    actor_id=UserId("00000000-0000-4000-8000-000000000007"),
)
ACTOR = ActorContext(
    APPROVER,
    AuthenticationMethod.OIDC,
    issuer="https://issuer.example",
    external_subject="approver",
)


def _proposal() -> ActionProposal:
    return ActionProposal(
        PROPOSAL_ID,
        SCOPE,
        IncidentReference(IncidentId("00000000-0000-4000-8000-000000000008"), SCOPE),
        TriageRunReference(TriageRunId("00000000-0000-4000-8000-000000000009"), SCOPE),
        ActionProposalType.ACKNOWLEDGE_INCIDENT,
        ActionTarget(
            ActionTargetType.INCIDENT,
            "00000000-0000-4000-8000-000000000008",
            "aira",
            ActionTargetProvenance.INCIDENT,
        ),
        "Acknowledge incident",
        "Display only",
        AcknowledgeIncidentParameters(),
        ActionRiskLevel.LOW,
        ActionReversibility.REVERSIBLE,
        ActionPolicyStatus.ALLOWED_FOR_REVIEW,
        ActionPolicyReason.READY_FOR_REVIEW,
        ActionProposalState.READY_FOR_REVIEW,
        APPROVER,
        NOW,
        NOW,
        1,
        "a" * 64,
        "b" * 64,
    )


def _approval() -> Approval:
    return Approval.request(
        id=APPROVAL_ID,
        proposal=_proposal(),
        requested_by=REQUESTER,
        requested_at=NOW,
        expires_at=NOW + timedelta(minutes=20),
    ).approve(APPROVER, at=NOW + timedelta(minutes=1))


def _intent() -> ExecutionIntent:
    proposal = _proposal()
    approval = _approval()
    return ExecutionIntent(
        INTENT_ID,
        SCOPE,
        proposal.incident,
        proposal.triage_run,
        proposal.reference,
        approval.id,
        1,
        1,
        "a" * 64,
        "b" * 64,
        approval.state_version,
        approval_binding_hash(approval),
        APPROVER,
        approval.decided_at,
        ConnectorKind.INTERNAL,
        OperationKind.ACKNOWLEDGE_INCIDENT,
        "aira",
        proposal.target,
        proposal.parameters,
        1,
        ActionRiskLevel.LOW,
        ActionReversibility.REVERSIBLE,
        1,
        ExecutionIntentState.PREPARED,
        "",
        APPROVER,
        NOW + timedelta(minutes=2),
        NOW + timedelta(minutes=2),
        NOW + timedelta(minutes=32),
    )


class Service:
    def __init__(self) -> None:
        self.calls = []

    def prepare(self, actor, organization_id, workspace_id, approval_id):
        self.calls.append("prepare")
        return _intent()

    def get(self, actor, organization_id, workspace_id, intent_id):
        self.calls.append("get")
        return _intent()

    def list_for_proposal(self, actor, organization_id, workspace_id, proposal_id):
        self.calls.append("list")
        return (_intent(),)

    def cancel(self, actor, organization_id, workspace_id, intent_id, *, reason):
        self.calls.append(("cancel", reason))
        intent = _intent()
        return intent.cancel(at=NOW + timedelta(minutes=3), reason=reason)


def _scope(path: str) -> str:
    return f"/v3/organizations/{ORG}/workspaces/{WORKSPACE}{path}"


def test_intent_routes_are_identifier_only_and_have_no_execution_endpoint() -> None:
    service = Service()
    app = FastAPI()
    app.include_router(
        build_hosted_incident_router(object(), lambda: ACTOR, execution_intents=service)
    )
    client = TestClient(app)

    responses = (
        client.post(_scope(f"/approvals/{APPROVAL_ID}/execution-intent")),
        client.get(_scope(f"/execution-intents/{INTENT_ID}")),
        client.get(_scope(f"/action-proposals/{PROPOSAL_ID}/execution-intents")),
        client.post(
            _scope(f"/execution-intents/{INTENT_ID}/cancel"),
            json={"reason": "Target changed"},
        ),
    )

    assert all(response.status_code == 200 for response in responses)
    payload = responses[0].json()
    assert payload["intent_hash"] == _intent().intent_hash
    assert payload["validation_status"] == "passed"
    assert payload["execution_status"] == "not_executed"
    assert service.calls == ["prepare", "get", "list", ("cancel", "Target changed")]
    paths = app.openapi()["paths"]
    assert not any(
        forbidden in path
        for path in paths
        for forbidden in ("/execute", "/run", "/apply", "/remediate")
    )


def test_cancel_rejects_empty_reason_and_prepare_rejects_payload() -> None:
    service = Service()
    app = FastAPI()
    app.include_router(
        build_hosted_incident_router(object(), lambda: ACTOR, execution_intents=service)
    )
    client = TestClient(app)

    assert (
        client.post(
            _scope(f"/execution-intents/{INTENT_ID}/cancel"), json={"reason": ""}
        ).status_code
        == 422
    )
    assert (
        client.post(
            _scope(f"/approvals/{APPROVAL_ID}/execution-intent"),
            json={"provider_request": {"command": "anything"}},
        ).status_code
        == 422
    )
    assert service.calls == []
