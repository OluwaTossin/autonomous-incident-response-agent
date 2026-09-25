"""Read-only hosted action proposal API contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.hosted_incidents import build_hosted_incident_router
from app.auth.context import ActorContext, AuthenticationMethod
from app.authorization.service import AuthorizationDenied
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
)
from app.domain.common import ActorKind, ActorReference, WorkspaceScope
from app.domain.identifiers import (
    ActionId,
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
INCIDENT = IncidentId("00000000-0000-4000-8000-000000000003")
RUN = TriageRunId("00000000-0000-4000-8000-000000000004")
PROPOSAL = ActionId("00000000-0000-4000-8000-000000000005")
SCOPE = WorkspaceScope(ORG, WORKSPACE)
ACTOR = ActorContext(
    ActorReference(
        ActorKind.HUMAN,
        actor_id=UserId("00000000-0000-4000-8000-000000000006"),
    ),
    AuthenticationMethod.OIDC,
    issuer="https://issuer.example",
    external_subject="viewer",
)


def _proposal() -> ActionProposal:
    return ActionProposal(
        PROPOSAL,
        SCOPE,
        IncidentReference(INCIDENT, SCOPE),
        TriageRunReference(RUN, SCOPE),
        ActionProposalType.ACKNOWLEDGE_INCIDENT,
        ActionTarget(
            ActionTargetType.INCIDENT,
            str(INCIDENT),
            "aira",
            ActionTargetProvenance.INCIDENT,
        ),
        "Acknowledge the incident",
        "Derived deterministically from the completed triage recommendation.",
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
        source_recommendation="Acknowledge incident",
    )


class ActionService:
    def list_for_incident(self, actor, organization_id, workspace_id, incident_id):
        assert actor is ACTOR
        assert (organization_id, workspace_id, incident_id) == (
            ORG,
            WORKSPACE,
            INCIDENT,
        )
        return (_proposal(),)

    def list_for_triage_run(self, actor, organization_id, workspace_id, run_id):
        assert actor is ACTOR
        assert (organization_id, workspace_id, run_id) == (ORG, WORKSPACE, RUN)
        return (_proposal(),)

    def get(self, actor, organization_id, workspace_id, proposal_id):
        assert proposal_id == PROPOSAL
        return _proposal()


def _client(action_service=None) -> TestClient:
    application = FastAPI()
    application.include_router(
        build_hosted_incident_router(
            object(),
            lambda: ACTOR,
            action_proposals=action_service or ActionService(),
        )
    )
    return TestClient(application)


def _scope(path: str) -> str:
    return f"/v3/organizations/{ORG}/workspaces/{WORKSPACE}{path}"


def test_lists_safe_policy_evaluated_proposals_for_run_and_incident() -> None:
    client = _client()

    run_response = client.get(_scope(f"/triage-runs/{RUN}/action-proposals"))
    incident_response = client.get(_scope(f"/incidents/{INCIDENT}/action-proposals"))

    assert run_response.status_code == 200
    assert incident_response.status_code == 200
    payload = run_response.json()[0]
    assert payload["action_proposal_id"] == str(PROPOSAL)
    assert payload["policy_status"] == "allowed_for_review"
    assert payload["policy_reason"] == "ready_for_review"
    assert payload["parameters"] == {"schema_version": 1}
    assert "source_recommendation" not in payload


def test_get_is_read_only_and_no_create_approve_or_execute_route_exists() -> None:
    client = _client()
    response = client.get(_scope(f"/action-proposals/{PROPOSAL}"))
    paths = client.app.openapi()["paths"]

    assert response.status_code == 200
    proposal_path = (
        "/v3/organizations/{organization_id}/workspaces/{workspace_id}"
        "/action-proposals/{proposal_id}"
    )
    assert set(paths[proposal_path]) == {"get"}
    assert not any("execute" in path or "approve" in path for path in paths)


def test_unauthorized_proposal_read_is_forbidden() -> None:
    class DeniedActionService(ActionService):
        def get(self, actor, organization_id, workspace_id, proposal_id):
            raise AuthorizationDenied("Access denied")

    response = _client(DeniedActionService()).get(
        _scope(f"/action-proposals/{PROPOSAL}")
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "forbidden"
