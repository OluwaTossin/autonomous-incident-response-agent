"""Controlled action proposal normalization, policy, and service tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.application.actions import (
    ActionPolicyEvaluator,
    ActionProposalGenerationError,
    AwsTargetAuthority,
    HostedActionProposalService,
    NormalizedAction,
    normalize_recommendation,
)
from app.auth.context import ActorContext, AuthenticationMethod
from app.authorization.permissions import Permission
from app.authorization.service import (
    AuthorizationService,
    HumanAuthorizationFacts,
)
from app.domain.actions import (
    ActionPolicyReason,
    ActionPolicyStatus,
    ActionProposalType,
    ActionReversibility,
    ActionRiskLevel,
    ActionTarget,
    ActionTargetProvenance,
    ActionTargetType,
    RestartWorkloadParameters,
)
from app.domain.common import (
    ActorKind,
    ActorReference,
    CorrelationContext,
    WorkspaceScope,
)
from app.domain.identifiers import (
    CorrelationId,
    IncidentId,
    IntegrationId,
    MembershipId,
    OrganizationId,
    TriageRunId,
    UserId,
    WorkspaceId,
)
from app.domain.incidents import (
    Incident,
    IncidentSource,
    IncidentState,
    TriageRun,
    TriageRunState,
)
from app.domain.tenancy import MembershipRole, WorkspaceAccessMode
from app.models.incident import IncidentPayload
from app.models.triage import TriageOutput

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
ORG = OrganizationId("00000000-0000-4000-8000-000000000001")
WORKSPACE = WorkspaceId("00000000-0000-4000-8000-000000000002")
SCOPE = WorkspaceScope(ORG, WORKSPACE)


def _actor() -> ActorContext:
    return ActorContext(
        ActorReference(
            ActorKind.HUMAN,
            actor_id=UserId("00000000-0000-4000-8000-000000000003"),
        ),
        AuthenticationMethod.OIDC,
        issuer="https://issuer.example",
        external_subject="operator",
    )


class Facts:
    def human_facts(self, actor, organization_id, workspace_id):
        if organization_id != ORG or workspace_id != WORKSPACE:
            return None
        return HumanAuthorizationFacts(
            MembershipId("00000000-0000-4000-8000-000000000004"),
            MembershipRole.OPERATOR,
            WorkspaceAccessMode.ALL,
            True,
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


def _incident() -> Incident:
    incident_id = IncidentId("00000000-0000-4000-8000-000000000010")
    return Incident(
        incident_id,
        SCOPE,
        IncidentPayload(
            alert_title="Checkout latency",
            service_name="checkout-api",
            environment="production",
            logs="timeouts",
            metric_summary="p95 high",
            time_of_occurrence=NOW.isoformat(),
        ),
        IncidentSource("manual", "operator", NOW),
        IncidentState.OPEN,
        _actor().actor,
        NOW,
        NOW,
        CorrelationContext(
            CorrelationId("00000000-0000-4000-8000-000000000011"),
            incident_id=incident_id,
        ),
    )


def _run(*actions: str, suffix: int = 20) -> TriageRun:
    incident = _incident()
    run_id = TriageRunId(f"00000000-0000-4000-8000-{suffix:012d}")
    correlation = CorrelationContext(
        CorrelationId(f"00000000-0000-4000-8000-{suffix + 1:012d}"),
        incident_id=incident.id,
        triage_run_id=run_id,
    )
    return TriageRun(
        run_id,
        SCOPE,
        incident.reference,
        TriageRunState.SUCCEEDED,
        _actor().actor,
        NOW,
        NOW,
        correlation,
        started_at=NOW,
        completed_at=NOW,
        result=TriageOutput(
            incident_summary="Checkout is degraded",
            service_name="checkout-api",
            severity="HIGH",
            likely_root_cause="Dependency saturation",
            recommended_actions=list(actions),
            escalate=True,
            confidence=0.8,
        ),
    )


class MappingRepo:
    def __init__(self, values):
        self.values = values

    def get(self, identifier, *, for_update=False):
        return self.values.get(identifier)


class ProposalRepo:
    def __init__(self):
        self.values = {}

    def create_or_get(self, proposal):
        key = (
            proposal.triage_run.id,
            proposal.source_result_hash,
            proposal.normalized_action_hash,
        )
        if key in self.values:
            return self.values[key], False
        self.values[key] = proposal
        return proposal, True

    def get(self, proposal_id):
        return next(
            (item for item in self.values.values() if item.id == proposal_id), None
        )

    def list_for_incident(self, incident_id):
        return [
            item for item in self.values.values() if item.incident.id == incident_id
        ]

    def list_for_triage_run(self, run_id):
        return [item for item in self.values.values() if item.triage_run.id == run_id]


class AuditRepo:
    def __init__(self):
        self.values = []

    def add(self, event):
        self.values.append(event)


class Store:
    def __init__(self, run):
        incident = _incident()
        self.incidents = MappingRepo({incident.id: incident})
        self.triage_runs = MappingRepo({run.id: run})
        self.action_proposals = ProposalRepo()
        self.audit_events = AuditRepo()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None


def test_unknown_recommendation_remains_manual_guidance() -> None:
    candidate = normalize_recommendation(_incident(), "Review database pool saturation")
    context = _authorization().authorize(
        _actor(), ORG, Permission.ACTION_PROPOSE, workspace_id=WORKSPACE
    )
    decision = ActionPolicyEvaluator().evaluate(context, candidate)

    assert candidate.proposal_type is ActionProposalType.MANUAL_INVESTIGATION
    assert decision.status is ActionPolicyStatus.MANUAL_ONLY
    assert decision.reason is ActionPolicyReason.MANUAL_GUIDANCE


def test_known_mutation_is_typed_but_ambiguous_target_stays_manual() -> None:
    candidate = normalize_recommendation(
        _incident(), "Roll back checkout to revision release-42"
    )
    context = _authorization().authorize(
        _actor(), ORG, Permission.ACTION_PROPOSE, workspace_id=WORKSPACE
    )
    decision = ActionPolicyEvaluator().evaluate(context, candidate)

    assert candidate.proposal_type is ActionProposalType.ROLLBACK_DEPLOYMENT
    assert candidate.risk_level is ActionRiskLevel.HIGH
    assert candidate.reversibility is ActionReversibility.PARTIALLY_REVERSIBLE
    assert decision.status is ActionPolicyStatus.MANUAL_ONLY
    assert decision.reason is ActionPolicyReason.UNTRUSTED_TARGET


def test_command_like_recommendation_is_blocked_and_not_retained() -> None:
    candidate = normalize_recommendation(
        _incident(), "kubectl rollout restart deployment checkout"
    )
    context = _authorization().authorize(
        _actor(), ORG, Permission.ACTION_PROPOSE, workspace_id=WORKSPACE
    )
    decision = ActionPolicyEvaluator().evaluate(context, candidate)

    assert candidate.source_recommendation is None
    assert decision.status is ActionPolicyStatus.BLOCKED
    assert decision.reason is ActionPolicyReason.UNSAFE_RECOMMENDATION


def test_policy_blocks_cross_account_and_region_targets() -> None:
    integration_id = IntegrationId("00000000-0000-4000-8000-000000000030")
    target = ActionTarget(
        ActionTargetType.AWS_RESOURCE,
        "arn:aws:ecs:eu-west-2:999999999999:service/cluster/checkout",
        "aws",
        ActionTargetProvenance.OPERATIONAL_CONTEXT,
        integration_id,
        "999999999999",
        "eu-west-2",
    )
    candidate = NormalizedAction(
        SCOPE,
        ActionProposalType.RESTART_WORKLOAD,
        target,
        "Review workload restart",
        "Trusted target candidate",
        RestartWorkloadParameters(),
        ActionRiskLevel.MEDIUM,
        ActionReversibility.PARTIALLY_REVERSIBLE,
        "Restart checkout",
    )
    context = _authorization().authorize(
        _actor(), ORG, Permission.ACTION_PROPOSE, workspace_id=WORKSPACE
    )
    decision = ActionPolicyEvaluator().evaluate(
        context,
        candidate,
        aws_authorities=(
            AwsTargetAuthority(
                integration_id,
                "123456789012",
                frozenset({"eu-west-2"}),
                True,
            ),
        ),
    )
    assert decision.reason is ActionPolicyReason.CROSS_ACCOUNT_TARGET


def test_generation_is_idempotent_and_preserves_retriage_history() -> None:
    first = _run("Acknowledge incident", "Review database pool saturation")
    store = Store(first)
    service = HostedActionProposalService(
        _authorization(), lambda context: store, clock=lambda: NOW
    )

    generated = service.generate_for_completed_run(_actor(), ORG, WORKSPACE, first.id)
    repeated = service.generate_for_completed_run(_actor(), ORG, WORKSPACE, first.id)
    second = _run("Acknowledge incident", suffix=40)
    store.triage_runs.values[second.id] = second
    retriage = service.generate_for_completed_run(_actor(), ORG, WORKSPACE, second.id)

    assert generated == repeated
    assert len(generated) == 2
    assert len(retriage) == 1
    assert len(store.action_proposals.values) == 3
    assert len(store.audit_events.values) == 3


def test_generation_rejects_non_successful_run() -> None:
    completed = _run("Acknowledge incident")
    failed = TriageRun(
        completed.id,
        completed.scope,
        completed.incident,
        TriageRunState.FAILED,
        completed.created_by,
        completed.created_at,
        completed.updated_at,
        completed.correlation,
        started_at=NOW,
        completed_at=NOW,
        error_message="failed",
        error_code="failed",
        error_category="internal",
        error_retryable=False,
    )
    store = Store(failed)
    service = HostedActionProposalService(_authorization(), lambda context: store)

    with pytest.raises(ActionProposalGenerationError):
        service.generate_for_completed_run(_actor(), ORG, WORKSPACE, failed.id)
