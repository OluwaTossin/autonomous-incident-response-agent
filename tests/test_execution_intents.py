"""Immutable execution-intent and deterministic connector tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.application.execution_intents import (
    ExecutionIntentConflict,
    ExecutionIntentValidationError,
    HostedExecutionIntentService,
    IntentValidationCode,
)
from app.auth.context import ActorContext, AuthenticationMethod, trusted_system_actor
from app.authorization.service import (
    AuthorizationDenied,
    AuthorizationService,
    HumanAuthorizationFacts,
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
    Approval,
)
from app.domain.common import ActorKind, ActorReference, WorkspaceScope
from app.domain.execution import ExecutionIntentState, canonical_intent_hash
from app.domain.identifiers import (
    ActionId,
    ApprovalId,
    IncidentId,
    IntegrationId,
    MembershipId,
    OrganizationId,
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
ADMIN_ID = UserId("00000000-0000-4000-8000-000000000005")
VIEWER_ID = UserId("00000000-0000-4000-8000-000000000006")


def _human(user_id: UserId) -> ActorContext:
    return ActorContext(
        ActorReference(ActorKind.HUMAN, actor_id=user_id),
        AuthenticationMethod.OIDC,
        issuer="https://issuer.example",
        external_subject=str(user_id),
    )


REQUESTER = _human(REQUESTER_ID)
APPROVER = _human(APPROVER_ID)
ADMIN = _human(ADMIN_ID)
VIEWER = _human(VIEWER_ID)
SYSTEM = trusted_system_actor(
    system_name="aira-worker",
    workload_issuer="https://workload.example",
    workload_subject="worker",
)


class Facts:
    def human_facts(self, actor, organization_id, workspace_id):
        roles = {
            REQUESTER_ID: MembershipRole.ADMIN,
            APPROVER_ID: MembershipRole.ADMIN,
            ADMIN_ID: MembershipRole.ADMIN,
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
    return AuthorizationService(Facts(), Resources())


def _proposal(**changes) -> ActionProposal:
    proposal = ActionProposal(
        ActionId("00000000-0000-4000-8000-000000000010"),
        SCOPE,
        IncidentReference(IncidentId("00000000-0000-4000-8000-000000000011"), SCOPE),
        TriageRunReference(TriageRunId("00000000-0000-4000-8000-000000000012"), SCOPE),
        ActionProposalType.ACKNOWLEDGE_INCIDENT,
        ActionTarget(
            ActionTargetType.INCIDENT,
            "00000000-0000-4000-8000-000000000011",
            "aira",
            ActionTargetProvenance.INCIDENT,
        ),
        "Acknowledge the incident",
        "Display only; never interpreted by the connector.",
        AcknowledgeIncidentParameters(),
        ActionRiskLevel.LOW,
        ActionReversibility.REVERSIBLE,
        ActionPolicyStatus.ALLOWED_FOR_REVIEW,
        ActionPolicyReason.READY_FOR_REVIEW,
        ActionProposalState.READY_FOR_REVIEW,
        SYSTEM.actor,
        NOW,
        NOW,
        1,
        "a" * 64,
        "b" * 64,
    )
    return replace(proposal, **changes)


def _approval(proposal: ActionProposal, **changes) -> Approval:
    requested = Approval.request(
        id=ApprovalId("00000000-0000-4000-8000-000000000013"),
        proposal=proposal,
        requested_by=REQUESTER.actor,
        requested_at=NOW,
        expires_at=NOW + timedelta(minutes=20),
    )
    approved = requested.approve(APPROVER.actor, at=NOW + timedelta(minutes=1))
    return replace(approved, **changes)


class Repository:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, identifier, *, for_update=False):
        return self.values.get(identifier)


class IntentRepository(Repository):
    def create_or_get(self, intent):
        existing = self.get_for_approval(intent.approval_id)
        if existing is not None:
            return existing, False
        self.values[intent.id] = intent
        return intent, True

    def get_for_approval(self, approval_id, *, for_update=False):
        return next(
            (item for item in self.values.values() if item.approval_id == approval_id),
            None,
        )

    def list_for_proposal(self, proposal_id, *, for_update=False):
        return [item for item in self.values.values() if item.action.id == proposal_id]

    def save_state(self, intent, *, expected_version):
        current = self.values[intent.id]
        if current.state_version != expected_version:
            raise RuntimeError("Execution intent state changed concurrently")
        self.values[intent.id] = intent


class AuditRepository:
    def __init__(self):
        self.values = []

    def add(self, event):
        self.values.append(event)


class Store:
    def __init__(self, proposal, approval):
        self.action_proposals = Repository({proposal.id: proposal})
        self.approvals = Repository({approval.id: approval})
        self.execution_intents = IntentRepository()
        self.audit_events = AuditRepository()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None


def _service(store: Store, *, now=NOW + timedelta(minutes=2)):
    return HostedExecutionIntentService(
        _authorization(), lambda context: store, clock=lambda: now
    )


def test_approved_exact_proposal_prepares_one_immutable_intent_idempotently() -> None:
    proposal = _proposal()
    approval = _approval(proposal)
    store = Store(proposal, approval)

    first = _service(store).prepare(ADMIN, ORG, WORKSPACE, approval.id)
    second = _service(store).prepare(ADMIN, ORG, WORKSPACE, approval.id)

    assert first == second
    assert first.action.id == proposal.id
    assert first.approval_id == approval.id
    assert first.target == proposal.target
    assert first.parameters == proposal.parameters
    assert first.intent_hash == canonical_intent_hash(first)
    assert first.connector_kind.value == "internal"
    assert first.operation_kind.value == "acknowledge_incident"
    assert len(store.execution_intents.values) == 1
    assert [event.event_type for event in store.audit_events.values] == [
        "execution_intent.connector_validation_passed",
        "execution_intent.prepared",
    ]


@pytest.mark.parametrize(
    ("approval_change", "proposal_change", "code"),
    [
        ({"state": "requested"}, {}, IntentValidationCode.APPROVAL_INVALID),
        (
            {},
            {"lifecycle_state": ActionProposalState.SUPERSEDED},
            IntentValidationCode.PROPOSAL_STALE,
        ),
        (
            {},
            {
                "policy_status": ActionPolicyStatus.MANUAL_ONLY,
                "policy_reason": ActionPolicyReason.MANUAL_GUIDANCE,
                "lifecycle_state": ActionProposalState.MANUAL_ONLY,
            },
            IntentValidationCode.PROPOSAL_STALE,
        ),
    ],
)
def test_invalid_approval_or_proposal_fails_closed(
    approval_change, proposal_change, code
) -> None:
    proposal = _proposal()
    approval = _approval(proposal)
    if approval_change:
        from app.domain.actions import ApprovalState

        approval_change["state"] = ApprovalState(approval_change["state"])
        approval_change.update(
            state_version=1, decided_by=None, decided_at=None, reason=None
        )
    store = Store(
        replace(proposal, **proposal_change), replace(approval, **approval_change)
    )

    with pytest.raises(ExecutionIntentValidationError) as captured:
        _service(store).prepare(ADMIN, ORG, WORKSPACE, approval.id)

    assert captured.value.code is code
    assert not store.execution_intents.values


def test_old_approval_and_binding_drift_are_rejected() -> None:
    proposal = _proposal()
    approval = _approval(proposal)
    with pytest.raises(ExecutionIntentValidationError) as captured:
        _service(
            Store(proposal, approval), now=approval.decided_at + timedelta(minutes=30)
        ).prepare(ADMIN, ORG, WORKSPACE, approval.id)
    assert captured.value.code is IntentValidationCode.APPROVAL_TOO_OLD

    drifted = replace(approval, normalized_action_hash="c" * 64)
    with pytest.raises(ExecutionIntentValidationError) as captured:
        _service(Store(proposal, drifted)).prepare(ADMIN, ORG, WORKSPACE, approval.id)
    assert captured.value.code is IntentValidationCode.APPROVAL_INVALID


def test_aws_or_manual_target_has_no_executable_connector() -> None:
    proposal = _proposal(
        target=ActionTarget(
            ActionTargetType.AWS_RESOURCE,
            "arn:aws:ecs:eu-west-2:123456789012:service/cluster/api",
            "aws",
            ActionTargetProvenance.OPERATIONAL_CONTEXT,
            integration_id=IntegrationId("00000000-0000-4000-8000-000000000014"),
            account_id="123456789012",
            region="eu-west-2",
        )
    )
    approval = _approval(proposal)
    store = Store(proposal, approval)

    with pytest.raises(ExecutionIntentValidationError) as captured:
        _service(store).prepare(ADMIN, ORG, WORKSPACE, approval.id)

    assert captured.value.code is IntentValidationCode.TARGET_NOT_AUTHORITATIVE
    assert not store.execution_intents.values
    assert store.audit_events.values[-1].event_type.endswith("validation_failed")


def test_deadline_invalidates_and_cancel_is_terminal() -> None:
    proposal = _proposal()
    approval = _approval(proposal)
    store = Store(proposal, approval)
    intent = _service(store).prepare(ADMIN, ORG, WORKSPACE, approval.id)

    invalidated = _service(store, now=intent.execute_before).get(
        VIEWER, ORG, WORKSPACE, intent.id
    )
    assert invalidated.lifecycle_state is ExecutionIntentState.INVALIDATED
    with pytest.raises(ExecutionIntentConflict):
        _service(store).cancel(
            ADMIN, ORG, WORKSPACE, invalidated.id, reason="No longer required"
        )

    fresh_proposal = replace(proposal, id=ActionId.new())
    fresh_approval = _approval(fresh_proposal, id=ApprovalId.new())
    fresh_store = Store(fresh_proposal, fresh_approval)
    fresh = _service(fresh_store).prepare(ADMIN, ORG, WORKSPACE, fresh_approval.id)
    cancelled = _service(fresh_store).cancel(
        ADMIN, ORG, WORKSPACE, fresh.id, reason="Target changed"
    )
    assert cancelled.lifecycle_state is ExecutionIntentState.CANCELLED


def test_viewer_can_read_but_cannot_prepare_and_system_has_no_implicit_grant() -> None:
    proposal = _proposal()
    approval = _approval(proposal)
    store = Store(proposal, approval)
    intent = _service(store).prepare(ADMIN, ORG, WORKSPACE, approval.id)

    assert _service(store).get(VIEWER, ORG, WORKSPACE, intent.id) == intent
    for actor in (VIEWER, SYSTEM):
        with pytest.raises(AuthorizationDenied):
            _service(store).prepare(actor, ORG, WORKSPACE, approval.id)


def test_canonical_hash_changes_with_execution_deadline() -> None:
    proposal = _proposal()
    approval = _approval(proposal)
    store = Store(proposal, approval)
    intent = _service(store).prepare(ADMIN, ORG, WORKSPACE, approval.id)

    changed = replace(
        intent,
        intent_hash="",
        execute_before=intent.execute_before + timedelta(minutes=1),
    )

    assert changed.intent_hash != intent.intent_hash
    assert "execute" not in dir(_service(store))
