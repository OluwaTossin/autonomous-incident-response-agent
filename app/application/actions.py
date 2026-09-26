"""Deterministic, proposal-only action application boundary."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, Self
from uuid import NAMESPACE_URL, uuid5

from app.auth.context import ActorContext
from app.authorization.permissions import Permission
from app.authorization.service import AuthorizationService, AuthorizedTenantContext
from app.domain.actions import (
    AcknowledgeIncidentParameters,
    ActionParameters,
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
    ManualInvestigationParameters,
    RestartWorkloadParameters,
    RollbackDeploymentParameters,
    ScaleDirection,
    ScaleWorkloadParameters,
    action_parameters_to_dict,
)
from app.domain.common import CorrelationContext, OrganizationScope, WorkspaceScope
from app.domain.events import AuditEvent
from app.domain.identifiers import (
    ActionId,
    AuditEventId,
    IncidentId,
    IntegrationId,
    OrganizationId,
    TriageRunId,
    WorkspaceId,
)
from app.domain.incidents import Incident, TriageRun, TriageRunState

_COMMAND_RE = re.compile(
    r"(?:^|\s)(?:sudo|bash|sh|zsh|kubectl|terraform|aws|curl|wget|powershell|"
    r"rm|systemctl|docker|helm|ansible|pulumi|gcloud|az|python|node|npm|yarn|git)"
    r"(?:\s|$)",
    re.IGNORECASE,
)
_SHELL_META_RE = re.compile(r"(?:&&|\|\||[;`]|\$\()")
_REVISION_RE = re.compile(
    r"\b(?:revision|version)\s+([A-Za-z0-9._:@/-]{1,160})\b", re.I
)
_DESIRED_COUNT_RE = re.compile(r"\bdesired\s+count\s+(?:to\s+)?(\d{1,4})\b", re.I)
_DELTA_RE = re.compile(r"\b(?:by|delta)\s+(\d{1,3})\b", re.I)


class ActionProposalNotFound(LookupError):
    pass


class ActionProposalGenerationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AwsTargetAuthority:
    integration_id: IntegrationId
    account_id: str
    regions: frozenset[str]
    ready: bool


@dataclass(frozen=True, slots=True)
class NormalizedAction:
    scope: WorkspaceScope
    proposal_type: ActionProposalType
    target: ActionTarget
    summary: str
    rationale: str
    parameters: ActionParameters
    risk_level: ActionRiskLevel
    reversibility: ActionReversibility
    source_recommendation: str | None
    unsafe_recommendation: bool = False


@dataclass(frozen=True, slots=True)
class ActionPolicyDecision:
    status: ActionPolicyStatus
    reason: ActionPolicyReason

    @property
    def lifecycle_state(self) -> ActionProposalState:
        return {
            ActionPolicyStatus.ALLOWED_FOR_REVIEW: ActionProposalState.READY_FOR_REVIEW,
            ActionPolicyStatus.BLOCKED: ActionProposalState.BLOCKED,
            ActionPolicyStatus.MANUAL_ONLY: ActionProposalState.MANUAL_ONLY,
        }[self.status]


class ActionPolicyEvaluator:
    """Fail-closed policy that never returns an approval decision."""

    def evaluate(
        self,
        context: AuthorizedTenantContext,
        candidate: NormalizedAction,
        *,
        aws_authorities: tuple[AwsTargetAuthority, ...] = (),
    ) -> ActionPolicyDecision:
        if context.workspace_id is None:
            return ActionPolicyDecision(
                ActionPolicyStatus.BLOCKED,
                ActionPolicyReason.CROSS_TENANT_TARGET,
            )
        expected = WorkspaceScope(context.organization_id, context.workspace_id)
        if candidate.scope != expected:
            return ActionPolicyDecision(
                ActionPolicyStatus.BLOCKED,
                ActionPolicyReason.CROSS_TENANT_TARGET,
            )
        if candidate.unsafe_recommendation:
            return ActionPolicyDecision(
                ActionPolicyStatus.BLOCKED,
                ActionPolicyReason.UNSAFE_RECOMMENDATION,
            )
        if candidate.proposal_type is ActionProposalType.MANUAL_INVESTIGATION:
            return ActionPolicyDecision(
                ActionPolicyStatus.MANUAL_ONLY,
                ActionPolicyReason.MANUAL_GUIDANCE,
            )
        if candidate.target.provenance is ActionTargetProvenance.UNKNOWN:
            return ActionPolicyDecision(
                ActionPolicyStatus.MANUAL_ONLY,
                ActionPolicyReason.UNKNOWN_TARGET,
            )
        if candidate.target.type is ActionTargetType.AWS_RESOURCE:
            decision = self._validate_aws_target(candidate.target, aws_authorities)
            if decision is not None:
                return decision
        elif candidate.proposal_type is not ActionProposalType.ACKNOWLEDGE_INCIDENT:
            return ActionPolicyDecision(
                ActionPolicyStatus.MANUAL_ONLY,
                ActionPolicyReason.UNTRUSTED_TARGET,
            )
        if candidate.reversibility is ActionReversibility.IRREVERSIBLE:
            return ActionPolicyDecision(
                ActionPolicyStatus.MANUAL_ONLY,
                ActionPolicyReason.IRREVERSIBLE,
            )
        if not _parameters_complete(candidate):
            return ActionPolicyDecision(
                ActionPolicyStatus.BLOCKED,
                ActionPolicyReason.PARAMETER_OUT_OF_BOUNDS,
            )
        return ActionPolicyDecision(
            ActionPolicyStatus.ALLOWED_FOR_REVIEW,
            ActionPolicyReason.READY_FOR_REVIEW,
        )

    @staticmethod
    def _validate_aws_target(
        target: ActionTarget,
        authorities: tuple[AwsTargetAuthority, ...],
    ) -> ActionPolicyDecision | None:
        authority = next(
            (
                item
                for item in authorities
                if item.integration_id == target.integration_id
            ),
            None,
        )
        if authority is None or not authority.ready:
            return ActionPolicyDecision(
                ActionPolicyStatus.BLOCKED,
                ActionPolicyReason.INTEGRATION_NOT_READY,
            )
        if target.account_id != authority.account_id:
            return ActionPolicyDecision(
                ActionPolicyStatus.BLOCKED,
                ActionPolicyReason.CROSS_ACCOUNT_TARGET,
            )
        if target.region not in authority.regions:
            return ActionPolicyDecision(
                ActionPolicyStatus.BLOCKED,
                ActionPolicyReason.REGION_NOT_ALLOWED,
            )
        return None


class ActionProposalRepository(Protocol):
    def create_or_get(
        self, proposal: ActionProposal
    ) -> tuple[ActionProposal, bool]: ...
    def get(self, proposal_id: ActionId) -> ActionProposal | None: ...
    def list_for_incident(
        self, incident_id: IncidentId
    ) -> Sequence[ActionProposal]: ...
    def list_for_triage_run(self, run_id: TriageRunId) -> Sequence[ActionProposal]: ...


class ActionProposalUnitOfWork(Protocol):
    incidents: object
    triage_runs: object
    action_proposals: ActionProposalRepository
    audit_events: object

    def __enter__(self) -> Self: ...
    def __exit__(self, exc_type, exc_value, traceback) -> None: ...


ActionProposalUnitOfWorkFactory = Callable[
    [AuthorizedTenantContext], ActionProposalUnitOfWork
]


class ActionProposalObserver(Protocol):
    def record(
        self,
        event: str,
        proposal_type: str,
        risk_level: str,
        policy_result: str,
    ) -> None: ...


class NoopActionProposalObserver:
    def record(
        self,
        event: str,
        proposal_type: str,
        risk_level: str,
        policy_result: str,
    ) -> None:
        return None


class HostedActionProposalService:
    def __init__(
        self,
        authorization: AuthorizationService,
        uow_factory: ActionProposalUnitOfWorkFactory,
        *,
        policy: ActionPolicyEvaluator = ActionPolicyEvaluator(),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        observer: ActionProposalObserver = NoopActionProposalObserver(),
    ) -> None:
        self._authorization = authorization
        self._uow_factory = uow_factory
        self._policy = policy
        self._clock = clock
        self._observer = observer

    def generate_for_completed_run(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        run_id: TriageRunId,
    ) -> tuple[ActionProposal, ...]:
        context = self._authorization.authorize(
            actor,
            organization_id,
            Permission.ACTION_PROPOSE,
            workspace_id=workspace_id,
        )
        now = self._clock()
        with self._uow_factory(context) as uow:
            run = uow.triage_runs.get(run_id)
            if (
                run is None
                or run.state is not TriageRunState.SUCCEEDED
                or run.result is None
            ):
                raise ActionProposalGenerationError(
                    "Action proposals require a completed successful triage run"
                )
            incident = uow.incidents.get(run.incident.id)
            if incident is None or incident.scope != run.scope:
                raise ActionProposalGenerationError(
                    "Proposal source incident is unavailable"
                )
            if len(run.result.recommended_actions) > 50:
                raise ActionProposalGenerationError(
                    "Triage result has too many recommendations"
                )
            result_hash = _result_hash(run)
            proposals: list[ActionProposal] = []
            seen: set[str] = set()
            for recommendation in run.result.recommended_actions:
                candidate = normalize_recommendation(incident, recommendation)
                identity_hash = _normalized_hash(candidate, result_hash)
                if identity_hash in seen:
                    continue
                seen.add(identity_hash)
                decision = self._policy.evaluate(context, candidate)
                proposal = _proposal(
                    context,
                    incident,
                    run,
                    candidate,
                    decision,
                    result_hash,
                    identity_hash,
                    now,
                )
                resolved, created = uow.action_proposals.create_or_get(proposal)
                proposals.append(resolved)
                if created:
                    uow.audit_events.add(_audit(context, resolved, run.correlation))
                    self._observe(resolved)
            return tuple(proposals)

    def get(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        proposal_id: ActionId,
    ) -> ActionProposal:
        context = self._read_context(actor, organization_id, workspace_id)
        with self._uow_factory(context) as uow:
            proposal = uow.action_proposals.get(proposal_id)
            if proposal is None:
                raise ActionProposalNotFound("Action proposal not found")
            return proposal

    def list_for_incident(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        incident_id: IncidentId,
    ) -> tuple[ActionProposal, ...]:
        context = self._read_context(actor, organization_id, workspace_id)
        with self._uow_factory(context) as uow:
            if uow.incidents.get(incident_id) is None:
                raise ActionProposalNotFound("Incident not found")
            return tuple(uow.action_proposals.list_for_incident(incident_id))

    def list_for_triage_run(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        run_id: TriageRunId,
    ) -> tuple[ActionProposal, ...]:
        context = self._read_context(actor, organization_id, workspace_id)
        with self._uow_factory(context) as uow:
            if uow.triage_runs.get(run_id) is None:
                raise ActionProposalNotFound("Triage run not found")
            return tuple(uow.action_proposals.list_for_triage_run(run_id))

    def _read_context(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
    ) -> AuthorizedTenantContext:
        return self._authorization.authorize(
            actor,
            organization_id,
            Permission.ACTION_READ,
            workspace_id=workspace_id,
        )

    def _observe(self, proposal: ActionProposal) -> None:
        self._observer.record(
            "action_policy_evaluation",
            proposal.proposal_type.value,
            proposal.risk_level.value,
            proposal.policy_status.value,
        )
        event = {
            ActionPolicyStatus.ALLOWED_FOR_REVIEW: "action_proposals_created",
            ActionPolicyStatus.BLOCKED: "action_proposals_blocked",
            ActionPolicyStatus.MANUAL_ONLY: "action_proposals_manual",
        }[proposal.policy_status]
        self._observer.record(
            event,
            proposal.proposal_type.value,
            proposal.risk_level.value,
            proposal.policy_status.value,
        )


def normalize_recommendation(
    incident: Incident,
    recommendation: str,
    *,
    authoritative_environment: str | None = None,
) -> NormalizedAction:
    source = recommendation.strip()
    if not source or len(source) > 2000:
        raise ActionProposalGenerationError("Triage recommendation is invalid")
    unsafe = bool(_COMMAND_RE.search(source) or _SHELL_META_RE.search(source))
    lower = source.casefold()
    proposal_type = _proposal_type(lower)
    target = ActionTarget(
        ActionTargetType.INCIDENT,
        str(incident.id),
        "aira",
        ActionTargetProvenance.INCIDENT,
    )
    parameters: ActionParameters
    summary: str
    reversibility: ActionReversibility
    if proposal_type is ActionProposalType.ACKNOWLEDGE_INCIDENT:
        parameters = AcknowledgeIncidentParameters()
        summary = "Acknowledge the incident"
        reversibility = ActionReversibility.REVERSIBLE
    elif proposal_type is ActionProposalType.RESTART_WORKLOAD:
        parameters = RestartWorkloadParameters()
        summary = "Review a workload restart"
        reversibility = ActionReversibility.PARTIALLY_REVERSIBLE
        target = _service_target(incident)
    elif proposal_type is ActionProposalType.SCALE_WORKLOAD:
        parameters = _scale_parameters(source)
        summary = "Review a workload scaling change"
        reversibility = ActionReversibility.REVERSIBLE
        target = _service_target(incident)
    elif proposal_type is ActionProposalType.ROLLBACK_DEPLOYMENT:
        match = _REVISION_RE.search(source)
        parameters = RollbackDeploymentParameters(match.group(1) if match else None)
        summary = "Review a deployment rollback"
        reversibility = ActionReversibility.PARTIALLY_REVERSIBLE
        target = _service_target(incident)
    else:
        parameters = ManualInvestigationParameters(
            "Review the original triage recommendation manually"
        )
        summary = "Manual investigation"
        reversibility = ActionReversibility.UNKNOWN
    return NormalizedAction(
        incident.scope,
        proposal_type,
        target,
        summary,
        (
            "The source recommendation resembled executable command content and was withheld."
            if unsafe
            else "Derived deterministically from the completed triage recommendation."
        ),
        parameters,
        _risk(proposal_type, authoritative_environment),
        reversibility,
        None if unsafe else source,
        unsafe,
    )


def _proposal_type(value: str) -> ActionProposalType:
    if value.startswith("acknowledge incident"):
        return ActionProposalType.ACKNOWLEDGE_INCIDENT
    if re.search(r"\b(?:restart|reboot)\b", value):
        return ActionProposalType.RESTART_WORKLOAD
    if re.search(r"\bscale\b", value):
        return ActionProposalType.SCALE_WORKLOAD
    if re.search(r"\b(?:rollback|roll back)\b", value):
        return ActionProposalType.ROLLBACK_DEPLOYMENT
    return ActionProposalType.MANUAL_INVESTIGATION


def _service_target(incident: Incident) -> ActionTarget:
    service = incident.payload.service_name.strip()
    return ActionTarget(
        ActionTargetType.SERVICE if service else ActionTargetType.INCIDENT,
        service or str(incident.id),
        "generic",
        ActionTargetProvenance.INCIDENT if service else ActionTargetProvenance.UNKNOWN,
    )


def _scale_parameters(value: str) -> ScaleWorkloadParameters:
    desired = _DESIRED_COUNT_RE.search(value)
    direction = None
    if re.search(r"\bscale\s+(?:up|out)\b", value, re.I):
        direction = ScaleDirection.UP
    elif re.search(r"\bscale\s+(?:down|in)\b", value, re.I):
        direction = ScaleDirection.DOWN
    delta = _DELTA_RE.search(value)
    try:
        return ScaleWorkloadParameters(
            desired_count=int(desired.group(1)) if desired else None,
            direction=direction,
            delta=int(delta.group(1)) if delta and direction else None,
        )
    except Exception:
        return ScaleWorkloadParameters()


def _risk(
    proposal_type: ActionProposalType,
    authoritative_environment: str | None,
) -> ActionRiskLevel:
    base = {
        ActionProposalType.ACKNOWLEDGE_INCIDENT: ActionRiskLevel.LOW,
        ActionProposalType.MANUAL_INVESTIGATION: ActionRiskLevel.LOW,
        ActionProposalType.RESTART_WORKLOAD: ActionRiskLevel.MEDIUM,
        ActionProposalType.SCALE_WORKLOAD: ActionRiskLevel.MEDIUM,
        ActionProposalType.ROLLBACK_DEPLOYMENT: ActionRiskLevel.HIGH,
    }[proposal_type]
    if authoritative_environment and authoritative_environment.casefold() in {
        "prod",
        "production",
    }:
        return {
            ActionRiskLevel.LOW: ActionRiskLevel.MEDIUM,
            ActionRiskLevel.MEDIUM: ActionRiskLevel.HIGH,
            ActionRiskLevel.HIGH: ActionRiskLevel.CRITICAL,
            ActionRiskLevel.CRITICAL: ActionRiskLevel.CRITICAL,
        }[base]
    return base


def _parameters_complete(candidate: NormalizedAction) -> bool:
    if candidate.proposal_type is ActionProposalType.SCALE_WORKLOAD:
        parameters = candidate.parameters
        if not isinstance(parameters, ScaleWorkloadParameters):
            return False
        return parameters.desired_count is not None or (
            parameters.direction is not None and parameters.delta is not None
        )
    if candidate.proposal_type is ActionProposalType.ROLLBACK_DEPLOYMENT:
        parameters = candidate.parameters
        if not isinstance(parameters, RollbackDeploymentParameters):
            return False
        return parameters.target_revision is not None
    return True


def _result_hash(run: TriageRun) -> str:
    if run.result is None:
        raise ValueError("A completed triage result is required for action proposals")
    encoded = json.dumps(
        run.result.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalized_hash(candidate: NormalizedAction, result_hash: str) -> str:
    canonical = {
        "proposal_type": candidate.proposal_type.value,
        "target_type": candidate.target.type.value,
        "target_identifier": candidate.target.identifier,
        "provider": candidate.target.provider,
        "parameters": action_parameters_to_dict(candidate.parameters),
        "source_result_hash": result_hash,
        "source_recommendation": candidate.source_recommendation,
        "unsafe": candidate.unsafe_recommendation,
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _proposal(
    context: AuthorizedTenantContext,
    incident: Incident,
    run: TriageRun,
    candidate: NormalizedAction,
    decision: ActionPolicyDecision,
    result_hash: str,
    normalized_hash: str,
    now: datetime,
) -> ActionProposal:
    identifier = uuid5(
        NAMESPACE_URL,
        f"aira:{run.id}:action-proposal:{result_hash}:{normalized_hash}",
    )
    return ActionProposal(
        id=ActionId(str(identifier)),
        scope=run.scope,
        incident=incident.reference,
        triage_run=run.reference,
        proposal_type=candidate.proposal_type,
        target=candidate.target,
        summary=candidate.summary,
        rationale=candidate.rationale,
        parameters=candidate.parameters,
        risk_level=candidate.risk_level,
        reversibility=candidate.reversibility,
        policy_status=decision.status,
        policy_reason=decision.reason,
        lifecycle_state=decision.lifecycle_state,
        created_by=context.actor,
        created_at=now,
        updated_at=now,
        source_result_version=1,
        source_result_hash=result_hash,
        normalized_action_hash=normalized_hash,
        source_recommendation=candidate.source_recommendation,
    )


def _audit(
    context: AuthorizedTenantContext,
    proposal: ActionProposal,
    correlation: CorrelationContext,
) -> AuditEvent:
    event_type = {
        ActionPolicyStatus.ALLOWED_FOR_REVIEW: "action_proposal.created",
        ActionPolicyStatus.BLOCKED: "action_proposal.blocked",
        ActionPolicyStatus.MANUAL_ONLY: "action_proposal.manual_only",
    }[proposal.policy_status]
    return AuditEvent(
        id=AuditEventId.new(),
        organization_scope=OrganizationScope(context.organization_id),
        workspace_scope=proposal.scope,
        event_type=event_type,
        target_type="action_proposal",
        target_id=str(proposal.id),
        actor=context.actor,
        occurred_at=proposal.created_at,
        correlation=correlation,
        details=(
            ("incident_id", str(proposal.incident.id)),
            ("triage_run_id", str(proposal.triage_run.id)),
            ("proposal_type", proposal.proposal_type.value),
            ("risk_level", proposal.risk_level.value),
            ("policy_status", proposal.policy_status.value),
            ("policy_reason", proposal.policy_reason.value),
            ("target_type", proposal.target.type.value),
            (
                "target_identifier_hash",
                hashlib.sha256(proposal.target.identifier.encode("utf-8")).hexdigest(),
            ),
        ),
    )
