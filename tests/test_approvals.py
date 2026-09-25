"""Human-only, proposal-bound approval workflow tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.application.approvals import (
    ApprovalConflict,
    ApprovalEligibilityError,
    HostedApprovalService,
)
from app.auth.context import (
    ActorContext,
    AuthenticationMethod,
    trusted_system_actor,
)
from app.authorization.service import (
    AuthorizationDenied,
    AuthorizationService,
    HumanAuthorizationFacts,
    SystemAuthorizationGrant,
)
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
    ApprovalState,
)
from app.domain.common import ActorKind, ActorReference, WorkspaceScope
from app.domain.identifiers import (
    ActionId,
    IncidentId,
    MembershipId,
    OrganizationId,
    ServiceAccountId,
    TriageRunId,
    UserId,
    WorkspaceId,
)
from app.domain.incidents import IncidentReference, TriageRunReference
from app.domain.tenancy import MembershipRole, WorkspaceAccessMode

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
ORG = OrganizationId("00000000-0000-4000-8000-000000000001")
WORKSPACE = WorkspaceId("00000000-0000-4000-8000-000000000002")
SCOPE = WorkspaceScope(ORG, WORKSPACE)
REQUESTER_ID = UserId("00000000-0000-4000-8000-000000000003")
APPROVER_ID = UserId("00000000-0000-4000-8000-000000000004")
VIEWER_ID = UserId("00000000-0000-4000-8000-000000000005")


def _human(user_id: UserId) -> ActorContext:
    return ActorContext(
        ActorReference(ActorKind.HUMAN, actor_id=user_id),
        AuthenticationMethod.OIDC,
        issuer="https://issuer.example",
        external_subject=str(user_id),
    )


REQUESTER = _human(REQUESTER_ID)
APPROVER = _human(APPROVER_ID)
VIEWER = _human(VIEWER_ID)
SYSTEM = trusted_system_actor(
    system_name="aira-worker",
    workload_issuer="https://workload.example",
    workload_subject="worker",
)
SERVICE_ACCOUNT = ActorContext(
    ActorReference(
        ActorKind.SERVICE_ACCOUNT,
        actor_id=ServiceAccountId("00000000-0000-4000-8000-000000000006"),
    ),
    AuthenticationMethod.SERVICE_ACCOUNT,
    credential_id="credential",
)


class Facts:
    def human_facts(self, actor, organization_id, workspace_id):
        roles = {
            REQUESTER_ID: MembershipRole.ADMIN,
            APPROVER_ID: MembershipRole.ADMIN,
            VIEWER_ID: MembershipRole.VIEWER,
        }
        role = roles.get(actor.actor.actor_id)
        if role is None or organization_id != ORG or workspace_id != WORKSPACE:
            return None
        return HumanAuthorizationFacts(
            MembershipId.new(), role, WorkspaceAccessMode.ALL, True
        )

    def service_account_facts(self, actor, organization_id, workspace_id):
        return None

    def invited_membership_id(self, actor, organization_id):
        return None

    def visible_organization_ids(self, actor):
        return (ORG,)


class Resources:
    def is_active(self, organization_id, workspace_id):
        return organization_id == ORG and workspace_id == WORKSPACE


def _authorization() -> AuthorizationService:
    return AuthorizationService(
        Facts(),
        Resources(),
        system_grants=(
            SystemAuthorizationGrant(
                "aira-worker",
                "https://workload.example",
                "worker",
                ORG,
                frozenset(),
                frozenset({WORKSPACE}),
            ),
        ),
    )


def _proposal(**changes) -> ActionProposal:
    proposal = ActionProposal(
        id=ActionId("00000000-0000-4000-8000-000000000010"),
        scope=SCOPE,
        incident=IncidentReference(
            IncidentId("00000000-0000-4000-8000-000000000011"), SCOPE
        ),
        triage_run=TriageRunReference(
            TriageRunId("00000000-0000-4000-8000-000000000012"), SCOPE
        ),
        proposal_type=ActionProposalType.ACKNOWLEDGE_INCIDENT,
        target=ActionTarget(
            ActionTargetType.INCIDENT,
            "00000000-0000-4000-8000-000000000011",
            "aira",
            ActionTargetProvenance.INCIDENT,
        ),
        summary="Acknowledge the incident",
        rationale="Derived deterministically from completed triage.",
        parameters=AcknowledgeIncidentParameters(),
        risk_level=ActionRiskLevel.LOW,
        reversibility=ActionReversibility.REVERSIBLE,
        policy_status=ActionPolicyStatus.ALLOWED_FOR_REVIEW,
        policy_reason=ActionPolicyReason.READY_FOR_REVIEW,
        lifecycle_state=ActionProposalState.READY_FOR_REVIEW,
        created_by=SYSTEM.actor,
        created_at=NOW,
        updated_at=NOW,
        source_result_version=1,
        source_result_hash="a" * 64,
        normalized_action_hash="b" * 64,
    )
    return replace(proposal, **changes)


class ProposalRepository:
    def __init__(self, proposal):
        self.proposal = proposal

    def get(self, proposal_id, *, for_update=False):
        return self.proposal if proposal_id == self.proposal.id else None


class ApprovalRepository:
    def __init__(self):
        self.values = {}

    def create_or_get_active(self, approval):
        active = self.get_active_for_proposal(approval.action.id)
        if active is not None:
            return active, False
        self.values[approval.id] = approval
        return approval, True

    def get(self, approval_id, *, for_update=False):
        return self.values.get(approval_id)

    def get_active_for_proposal(self, proposal_id, *, for_update=False):
        return next(
            (
                item
                for item in self.values.values()
                if item.action.id == proposal_id
                and item.state is ApprovalState.REQUESTED
            ),
            None,
        )

    def list_for_proposal(self, proposal_id):
        return [item for item in self.values.values() if item.action.id == proposal_id]

    def list_due(self, at, *, limit):
        return [
            item
            for item in self.values.values()
            if item.state is ApprovalState.REQUESTED and item.expires_at <= at
        ][:limit]

    def save(self, approval, *, expected_version):
        current = self.values[approval.id]
        if current.state_version != expected_version:
            raise RuntimeError("Approval state changed concurrently")
        self.values[approval.id] = approval


class AuditRepository:
    def __init__(self):
        self.values = []

    def add(self, event):
        self.values.append(event)


class Store:
    def __init__(self, proposal):
        self.action_proposals = ProposalRepository(proposal)
        self.approvals = ApprovalRepository()
        self.audit_events = AuditRepository()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None


def _service(store: Store, *, now=NOW) -> HostedApprovalService:
    return HostedApprovalService(
        _authorization(),
        lambda context: store,
        approval_ttl=timedelta(minutes=30),
        clock=lambda: now,
    )


def test_request_is_eligible_idempotent_and_bound_to_exact_proposal() -> None:
    proposal = _proposal()
    store = Store(proposal)
    service = _service(store)

    first = service.request_approval(REQUESTER, ORG, WORKSPACE, proposal.id)
    second = service.request_approval(REQUESTER, ORG, WORKSPACE, proposal.id)

    assert first == second
    assert first.binds(proposal)
    assert first.requested_by == REQUESTER.actor
    assert first.expires_at == NOW + timedelta(minutes=30)
    assert len(store.approvals.values) == 1
    assert len(store.audit_events.values) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {
            "policy_status": ActionPolicyStatus.BLOCKED,
            "policy_reason": ActionPolicyReason.UNSAFE_RECOMMENDATION,
            "lifecycle_state": ActionProposalState.BLOCKED,
        },
        {
            "policy_status": ActionPolicyStatus.MANUAL_ONLY,
            "policy_reason": ActionPolicyReason.MANUAL_GUIDANCE,
            "lifecycle_state": ActionProposalState.MANUAL_ONLY,
        },
        {"lifecycle_state": ActionProposalState.SUPERSEDED},
        {"lifecycle_state": ActionProposalState.CANCELLED},
    ],
)
def test_ineligible_proposals_cannot_enter_approval(changes) -> None:
    proposal = _proposal(**changes)
    with pytest.raises(ApprovalEligibilityError):
        _service(Store(proposal)).request_approval(
            REQUESTER, ORG, WORKSPACE, proposal.id
        )


def test_distinct_authorized_human_approves_without_execution_state() -> None:
    proposal = _proposal()
    store = Store(proposal)
    requested = _service(store).request_approval(REQUESTER, ORG, WORKSPACE, proposal.id)

    approved = HostedApprovalService(
        _authorization(),
        lambda context: store,
        clock=lambda: NOW + timedelta(minutes=1),
    ).approve(APPROVER, ORG, WORKSPACE, requested.id, reason="Reviewed")

    assert approved.state is ApprovalState.APPROVED
    assert approved.decided_by == APPROVER.actor
    assert (
        store.action_proposals.proposal.lifecycle_state
        is ActionProposalState.READY_FOR_REVIEW
    )
    assert [event.event_type for event in store.audit_events.values] == [
        "approval.requested",
        "approval.approved",
    ]


def test_reject_requires_reason_and_is_terminal() -> None:
    proposal = _proposal()
    store = Store(proposal)
    requested = _service(store).request_approval(REQUESTER, ORG, WORKSPACE, proposal.id)
    later = HostedApprovalService(
        _authorization(),
        lambda context: store,
        clock=lambda: NOW + timedelta(minutes=1),
    )

    with pytest.raises(ValueError, match="reason"):
        later.reject(APPROVER, ORG, WORKSPACE, requested.id, reason="")
    rejected = later.reject(
        APPROVER, ORG, WORKSPACE, requested.id, reason="Target needs correction"
    )
    with pytest.raises(ApprovalConflict):
        later.approve(APPROVER, ORG, WORKSPACE, requested.id)
    assert rejected.state is ApprovalState.REJECTED


def test_self_viewer_service_and_system_decisions_fail_closed() -> None:
    proposal = _proposal()
    store = Store(proposal)
    requested = _service(store).request_approval(REQUESTER, ORG, WORKSPACE, proposal.id)
    service = _service(store, now=NOW + timedelta(minutes=1))

    for actor in (REQUESTER, VIEWER, SERVICE_ACCOUNT, SYSTEM):
        with pytest.raises((AuthorizationDenied, ApprovalConflict)):
            service.approve(actor, ORG, WORKSPACE, requested.id)
    assert store.approvals.values[requested.id].state is ApprovalState.REQUESTED


def test_exact_expiry_boundary_persists_expired_and_rejects_decision() -> None:
    proposal = _proposal()
    store = Store(proposal)
    requested = _service(store).request_approval(REQUESTER, ORG, WORKSPACE, proposal.id)

    with pytest.raises(ApprovalConflict, match="expired"):
        _service(store, now=requested.expires_at).approve(
            APPROVER, ORG, WORKSPACE, requested.id
        )
    assert store.approvals.values[requested.id].state is ApprovalState.EXPIRED


def test_stale_proposal_cancels_request_and_cannot_carry_forward() -> None:
    proposal = _proposal()
    store = Store(proposal)
    requested = _service(store).request_approval(REQUESTER, ORG, WORKSPACE, proposal.id)
    store.action_proposals.proposal = replace(
        proposal, lifecycle_state=ActionProposalState.SUPERSEDED
    )

    with pytest.raises(ApprovalConflict, match="stale"):
        _service(store, now=NOW + timedelta(minutes=1)).approve(
            APPROVER, ORG, WORKSPACE, requested.id
        )
    assert store.approvals.values[requested.id].state is ApprovalState.CANCELLED


def test_requester_can_cancel_but_cannot_cancel_terminal_decision() -> None:
    proposal = _proposal()
    store = Store(proposal)
    requested = _service(store).request_approval(REQUESTER, ORG, WORKSPACE, proposal.id)
    service = _service(store, now=NOW + timedelta(minutes=1))

    cancelled = service.cancel(
        REQUESTER, ORG, WORKSPACE, requested.id, reason="No longer needed"
    )
    assert cancelled.state is ApprovalState.CANCELLED
    with pytest.raises(ApprovalConflict):
        service.cancel(REQUESTER, ORG, WORKSPACE, requested.id)
