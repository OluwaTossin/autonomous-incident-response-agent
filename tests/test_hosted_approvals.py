"""Hosted human approval API contract tests."""

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
from app.domain.identifiers import (
    ActionId,
    ApprovalId,
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
PROPOSAL_ID = ActionId("00000000-0000-4000-8000-000000000003")
APPROVAL_ID = ApprovalId("00000000-0000-4000-8000-000000000004")
SCOPE = WorkspaceScope(ORG, WORKSPACE)
ACTOR = ActorContext(
    ActorReference(
        ActorKind.HUMAN,
        actor_id=UserId("00000000-0000-4000-8000-000000000005"),
    ),
    AuthenticationMethod.OIDC,
    issuer="https://issuer.example",
    external_subject="operator",
)


def _proposal() -> ActionProposal:
    return ActionProposal(
        PROPOSAL_ID,
        SCOPE,
        IncidentReference(IncidentId("00000000-0000-4000-8000-000000000006"), SCOPE),
        TriageRunReference(TriageRunId("00000000-0000-4000-8000-000000000007"), SCOPE),
        ActionProposalType.ACKNOWLEDGE_INCIDENT,
        ActionTarget(
            ActionTargetType.INCIDENT,
            "00000000-0000-4000-8000-000000000006",
            "aira",
            ActionTargetProvenance.INCIDENT,
        ),
        "Acknowledge the incident",
        "Derived deterministically from completed triage.",
        AcknowledgeIncidentParameters(),
        ActionRiskLevel.LOW,
        ActionReversibility.REVERSIBLE,
        ActionPolicyStatus.ALLOWED_FOR_REVIEW,
        ActionPolicyReason.READY_FOR_REVIEW,
        ActionProposalState.READY_FOR_REVIEW,
        ACTOR.actor,
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
        requested_by=ACTOR.actor,
        requested_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
    )


class ApprovalService:
    def __init__(self):
        self.calls = []

    def request_approval(self, actor, organization_id, workspace_id, proposal_id):
        self.calls.append("request")
        return _approval()

    def list_for_proposal(self, actor, organization_id, workspace_id, proposal_id):
        self.calls.append("list")
        return (_approval(),)

    def get_approval(self, actor, organization_id, workspace_id, approval_id):
        self.calls.append("get")
        return _approval()

    def approve(
        self, actor, organization_id, workspace_id, approval_id, *, reason=None
    ):
        self.calls.append(("approve", reason))
        return _approval()

    def reject(self, actor, organization_id, workspace_id, approval_id, *, reason):
        self.calls.append(("reject", reason))
        return _approval()

    def cancel(self, actor, organization_id, workspace_id, approval_id, *, reason=None):
        self.calls.append(("cancel", reason))
        return _approval()


def _client(service: ApprovalService) -> TestClient:
    application = FastAPI()
    application.include_router(
        build_hosted_incident_router(object(), lambda: ACTOR, approvals=service)
    )
    return TestClient(application)


def _scope(path: str) -> str:
    return f"/v3/organizations/{ORG}/workspaces/{WORKSPACE}{path}"


def test_request_list_get_and_decisions_are_approval_only() -> None:
    service = ApprovalService()
    client = _client(service)

    responses = (
        client.post(_scope(f"/action-proposals/{PROPOSAL_ID}/approval")),
        client.get(_scope(f"/action-proposals/{PROPOSAL_ID}/approvals")),
        client.get(_scope(f"/approvals/{APPROVAL_ID}")),
        client.post(
            _scope(f"/approvals/{APPROVAL_ID}/approve"), json={"reason": "Reviewed"}
        ),
        client.post(
            _scope(f"/approvals/{APPROVAL_ID}/reject"),
            json={"reason": "Target changed"},
        ),
        client.post(_scope(f"/approvals/{APPROVAL_ID}/cancel"), json={"reason": None}),
    )

    assert all(response.status_code == 200 for response in responses)
    assert responses[0].json()["state"] == "requested"
    assert responses[0].json()["source_result_hash"] == "a" * 64
    paths = client.app.openapi()["paths"]
    assert not any("execute" in path for path in paths)
    assert service.calls == [
        "request",
        "list",
        "get",
        ("approve", "Reviewed"),
        ("reject", "Target changed"),
        ("cancel", None),
    ]


def test_rejection_reason_is_required_and_payloads_are_bounded() -> None:
    response = _client(ApprovalService()).post(
        _scope(f"/approvals/{APPROVAL_ID}/reject"), json={"reason": ""}
    )

    assert response.status_code == 422
