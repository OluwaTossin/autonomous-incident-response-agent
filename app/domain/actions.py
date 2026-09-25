"""Typed action proposals and the future human-approval domain boundary."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import TypeAlias

from app.domain.common import (
    ActorKind,
    ActorReference,
    DomainInvariantError,
    WorkspaceScope,
    require_aware,
    require_transition,
    utc_now,
    validate_timestamps,
)
from app.domain.identifiers import ActionId, ApprovalId, IntegrationId
from app.domain.incidents import IncidentReference, TriageRunReference


class ActionProposalType(StrEnum):
    ACKNOWLEDGE_INCIDENT = "acknowledge_incident"
    MANUAL_INVESTIGATION = "manual_investigation"
    RESTART_WORKLOAD = "restart_workload"
    SCALE_WORKLOAD = "scale_workload"
    ROLLBACK_DEPLOYMENT = "rollback_deployment"


class ActionTargetType(StrEnum):
    INCIDENT = "incident"
    SERVICE = "service"
    AWS_RESOURCE = "aws_resource"


class ActionTargetProvenance(StrEnum):
    INCIDENT = "incident"
    OPERATIONAL_CONTEXT = "operational_context"
    UNKNOWN = "unknown"


class ActionRiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ActionReversibility(StrEnum):
    REVERSIBLE = "reversible"
    PARTIALLY_REVERSIBLE = "partially_reversible"
    IRREVERSIBLE = "irreversible"
    UNKNOWN = "unknown"


class ActionPolicyStatus(StrEnum):
    ALLOWED_FOR_REVIEW = "allowed_for_review"
    BLOCKED = "blocked"
    MANUAL_ONLY = "manual_only"


class ActionPolicyReason(StrEnum):
    READY_FOR_REVIEW = "ready_for_review"
    MANUAL_GUIDANCE = "manual_guidance"
    UNSAFE_RECOMMENDATION = "unsafe_recommendation"
    UNKNOWN_TARGET = "unknown_target"
    UNTRUSTED_TARGET = "untrusted_target"
    UNSUPPORTED_ACTION = "unsupported_action"
    IRREVERSIBLE = "irreversible"
    CROSS_TENANT_TARGET = "cross_tenant_target"
    CROSS_ACCOUNT_TARGET = "cross_account_target"
    REGION_NOT_ALLOWED = "region_not_allowed"
    INTEGRATION_NOT_READY = "integration_not_ready"
    PARAMETER_OUT_OF_BOUNDS = "parameter_out_of_bounds"


class ActionProposalState(StrEnum):
    READY_FOR_REVIEW = "ready_for_review"
    BLOCKED = "blocked"
    MANUAL_ONLY = "manual_only"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"


class ScaleDirection(StrEnum):
    UP = "up"
    DOWN = "down"


@dataclass(frozen=True, slots=True)
class ManualInvestigationParameters:
    instruction: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        instruction = self.instruction.strip()
        if not instruction or len(instruction) > 2000:
            raise DomainInvariantError("Manual investigation instruction is invalid")
        object.__setattr__(self, "instruction", instruction)


@dataclass(frozen=True, slots=True)
class AcknowledgeIncidentParameters:
    schema_version: int = 1


@dataclass(frozen=True, slots=True)
class RestartWorkloadParameters:
    schema_version: int = 1


@dataclass(frozen=True, slots=True)
class ScaleWorkloadParameters:
    desired_count: int | None = None
    direction: ScaleDirection | None = None
    delta: int | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.desired_count is not None and not 0 <= self.desired_count <= 1000:
            raise DomainInvariantError(
                "Scale desired_count is outside the supported bound"
            )
        if self.delta is not None and not 1 <= self.delta <= 100:
            raise DomainInvariantError("Scale delta is outside the supported bound")
        if self.direction is None and self.delta is not None:
            raise DomainInvariantError("Scale delta requires a direction")


@dataclass(frozen=True, slots=True)
class RollbackDeploymentParameters:
    target_revision: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.target_revision is not None:
            revision = self.target_revision.strip()
            if not revision or len(revision) > 160:
                raise DomainInvariantError("Rollback target revision is invalid")
            object.__setattr__(self, "target_revision", revision)


ActionParameters: TypeAlias = (
    ManualInvestigationParameters
    | AcknowledgeIncidentParameters
    | RestartWorkloadParameters
    | ScaleWorkloadParameters
    | RollbackDeploymentParameters
)


_PARAMETER_TYPES = {
    ActionProposalType.MANUAL_INVESTIGATION: ManualInvestigationParameters,
    ActionProposalType.ACKNOWLEDGE_INCIDENT: AcknowledgeIncidentParameters,
    ActionProposalType.RESTART_WORKLOAD: RestartWorkloadParameters,
    ActionProposalType.SCALE_WORKLOAD: ScaleWorkloadParameters,
    ActionProposalType.ROLLBACK_DEPLOYMENT: RollbackDeploymentParameters,
}


@dataclass(frozen=True, slots=True)
class ActionTarget:
    type: ActionTargetType
    identifier: str
    provider: str
    provenance: ActionTargetProvenance
    integration_id: IntegrationId | None = None
    account_id: str | None = None
    region: str | None = None

    def __post_init__(self) -> None:
        identifier = self.identifier.strip()
        provider = self.provider.strip().lower()
        if not identifier or len(identifier) > 1000:
            raise DomainInvariantError("Action target identifier is invalid")
        if not provider or len(provider) > 80:
            raise DomainInvariantError("Action target provider is invalid")
        if self.type is ActionTargetType.AWS_RESOURCE:
            if (
                self.integration_id is None
                or self.account_id is None
                or self.region is None
                or self.provenance is not ActionTargetProvenance.OPERATIONAL_CONTEXT
            ):
                raise DomainInvariantError(
                    "AWS targets require trusted integration provenance"
                )
        elif any((self.integration_id, self.account_id, self.region)):
            raise DomainInvariantError(
                "Only AWS targets may carry AWS authority metadata"
            )
        object.__setattr__(self, "identifier", identifier)
        object.__setattr__(self, "provider", provider)


@dataclass(frozen=True, slots=True)
class ActionReference:
    id: ActionId
    scope: WorkspaceScope


@dataclass(frozen=True, slots=True)
class ActionProposal:
    id: ActionId
    scope: WorkspaceScope
    incident: IncidentReference
    triage_run: TriageRunReference
    proposal_type: ActionProposalType
    target: ActionTarget
    summary: str
    rationale: str
    parameters: ActionParameters
    risk_level: ActionRiskLevel
    reversibility: ActionReversibility
    policy_status: ActionPolicyStatus
    policy_reason: ActionPolicyReason
    lifecycle_state: ActionProposalState
    created_by: ActorReference
    created_at: datetime
    updated_at: datetime
    source_result_version: int
    source_result_hash: str
    normalized_action_hash: str
    proposal_schema_version: int = 1
    source_recommendation: str | None = None

    def __post_init__(self) -> None:
        if self.scope != self.incident.scope or self.scope != self.triage_run.scope:
            raise DomainInvariantError(
                "Action proposal source must have the same workspace scope"
            )
        if not isinstance(self.parameters, _PARAMETER_TYPES[self.proposal_type]):
            raise DomainInvariantError(
                "Action proposal parameters do not match its type"
            )
        summary = self.summary.strip()
        rationale = self.rationale.strip()
        if not summary or len(summary) > 300:
            raise DomainInvariantError("Action proposal summary is invalid")
        if not rationale or len(rationale) > 2000:
            raise DomainInvariantError("Action proposal rationale is invalid")
        if self.source_recommendation is not None:
            recommendation = self.source_recommendation.strip()
            if not recommendation or len(recommendation) > 2000:
                raise DomainInvariantError("Source recommendation is invalid")
            object.__setattr__(self, "source_recommendation", recommendation)
        if self.source_result_version < 1 or self.proposal_schema_version != 1:
            raise DomainInvariantError("Action proposal schema version is invalid")
        for name, value in (
            ("source_result_hash", self.source_result_hash),
            ("normalized_action_hash", self.normalized_action_hash),
        ):
            if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise DomainInvariantError(f"{name} is invalid")
        validate_timestamps(self.created_at, self.updated_at)
        expected_state = {
            ActionPolicyStatus.ALLOWED_FOR_REVIEW: ActionProposalState.READY_FOR_REVIEW,
            ActionPolicyStatus.BLOCKED: ActionProposalState.BLOCKED,
            ActionPolicyStatus.MANUAL_ONLY: ActionProposalState.MANUAL_ONLY,
        }[self.policy_status]
        if self.lifecycle_state not in {
            expected_state,
            ActionProposalState.SUPERSEDED,
            ActionProposalState.CANCELLED,
        }:
            raise DomainInvariantError(
                "Action proposal lifecycle conflicts with policy"
            )
        if self.reversibility is ActionReversibility.IRREVERSIBLE and (
            self.policy_status is ActionPolicyStatus.ALLOWED_FOR_REVIEW
        ):
            raise DomainInvariantError(
                "Irreversible actions cannot be ready for review"
            )
        object.__setattr__(self, "summary", summary)
        object.__setattr__(self, "rationale", rationale)

    @property
    def reference(self) -> ActionReference:
        return ActionReference(self.id, self.scope)


class ApprovalState(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


_APPROVAL_TRANSITIONS = {
    ApprovalState.REQUESTED: frozenset(
        {
            ApprovalState.APPROVED,
            ApprovalState.REJECTED,
            ApprovalState.EXPIRED,
            ApprovalState.CANCELLED,
        }
    ),
    ApprovalState.APPROVED: frozenset(),
    ApprovalState.REJECTED: frozenset(),
    ApprovalState.EXPIRED: frozenset(),
    ApprovalState.CANCELLED: frozenset(),
}

APPROVAL_TERMINAL_STATES = frozenset(
    {
        ApprovalState.APPROVED,
        ApprovalState.REJECTED,
        ApprovalState.EXPIRED,
        ApprovalState.CANCELLED,
    }
)


@dataclass(frozen=True, slots=True)
class Approval:
    """A human decision bound to one immutable action proposal version."""

    id: ApprovalId
    scope: WorkspaceScope
    action: ActionReference
    proposal_schema_version: int
    source_result_version: int
    source_result_hash: str
    normalized_action_hash: str
    state: ApprovalState
    requested_by: ActorReference
    requested_at: datetime
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    state_version: int = 1
    decided_by: ActorReference | None = None
    decided_at: datetime | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.scope != self.action.scope:
            raise DomainInvariantError(
                "Approval and Action must have the same workspace scope"
            )
        if self.requested_by.kind is not ActorKind.HUMAN:
            raise DomainInvariantError("Approval requests require a human actor")
        if self.proposal_schema_version != 1 or self.source_result_version < 1:
            raise DomainInvariantError("Approval proposal binding version is invalid")
        for name, value in (
            ("source_result_hash", self.source_result_hash),
            ("normalized_action_hash", self.normalized_action_hash),
        ):
            if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise DomainInvariantError(f"Approval {name} is invalid")
        if self.state_version < 1:
            raise DomainInvariantError("Approval state_version must be positive")
        validate_timestamps(self.created_at, self.updated_at)
        require_aware(self.requested_at, "requested_at")
        require_aware(self.expires_at, "expires_at")
        if self.requested_at != self.created_at:
            raise DomainInvariantError("Approval requested_at must equal created_at")
        if self.expires_at <= self.requested_at:
            raise DomainInvariantError("Approval expires_at must follow requested_at")
        if self.decided_at is not None:
            require_aware(self.decided_at, "decided_at")
            if self.decided_at < self.created_at:
                raise DomainInvariantError(
                    "Approval decided_at cannot precede created_at"
                )
        terminal = self.state in APPROVAL_TERMINAL_STATES
        if terminal and self.decided_at is None:
            raise DomainInvariantError("Terminal approvals require decided_at")
        actor_decisions = {
            ApprovalState.APPROVED,
            ApprovalState.REJECTED,
            ApprovalState.CANCELLED,
        }
        if self.state in actor_decisions and self.decided_by is None:
            raise DomainInvariantError("Approval decision requires decided_by")
        if self.decided_by is not None and self.decided_by.kind is not ActorKind.HUMAN:
            raise DomainInvariantError("Approval decisions require a human actor")
        if self.state in {ApprovalState.APPROVED, ApprovalState.REJECTED} and (
            self.decided_by == self.requested_by
        ):
            raise DomainInvariantError(
                "Approval requester cannot decide their own request"
            )
        if self.state is ApprovalState.REJECTED and not self.reason:
            raise DomainInvariantError("Rejected approvals require a reason")
        if self.state in {ApprovalState.APPROVED, ApprovalState.REJECTED} and (
            self.decided_at is not None and self.decided_at >= self.expires_at
        ):
            raise DomainInvariantError("Expired approval requests cannot be decided")
        if self.state is ApprovalState.EXPIRED and (
            self.decided_at is not None and self.decided_at < self.expires_at
        ):
            raise DomainInvariantError("Approval cannot expire before expires_at")
        if self.reason is not None:
            reason = self.reason.strip()
            if not reason or len(reason) > 1000:
                raise DomainInvariantError("Approval decision reason is invalid")
            object.__setattr__(self, "reason", reason)
        if not terminal and any((self.decided_by, self.decided_at, self.reason)):
            raise DomainInvariantError(
                "Requested approvals cannot carry decision fields"
            )

    @classmethod
    def request(
        cls,
        *,
        id: ApprovalId,
        proposal: ActionProposal,
        requested_by: ActorReference,
        requested_at: datetime,
        expires_at: datetime,
    ) -> Approval:
        return cls(
            id=id,
            scope=proposal.scope,
            action=proposal.reference,
            proposal_schema_version=proposal.proposal_schema_version,
            source_result_version=proposal.source_result_version,
            source_result_hash=proposal.source_result_hash,
            normalized_action_hash=proposal.normalized_action_hash,
            state=ApprovalState.REQUESTED,
            requested_by=requested_by,
            requested_at=requested_at,
            created_at=requested_at,
            updated_at=requested_at,
            expires_at=expires_at,
        )

    def binds(self, proposal: ActionProposal) -> bool:
        return (
            self.action == proposal.reference
            and self.proposal_schema_version == proposal.proposal_schema_version
            and self.source_result_version == proposal.source_result_version
            and self.source_result_hash == proposal.source_result_hash
            and self.normalized_action_hash == proposal.normalized_action_hash
        )

    def approve(
        self,
        actor: ActorReference,
        *,
        at: datetime | None = None,
        reason: str | None = None,
    ) -> Approval:
        return self._decide(ApprovalState.APPROVED, actor=actor, at=at, reason=reason)

    def reject(
        self,
        actor: ActorReference,
        reason: str,
        *,
        at: datetime | None = None,
    ) -> Approval:
        return self._decide(ApprovalState.REJECTED, actor=actor, at=at, reason=reason)

    def expire(self, *, at: datetime | None = None) -> Approval:
        return self._decide(ApprovalState.EXPIRED, at=at)

    def cancel(
        self,
        actor: ActorReference,
        *,
        at: datetime | None = None,
        reason: str | None = None,
    ) -> Approval:
        return self._decide(ApprovalState.CANCELLED, actor=actor, at=at, reason=reason)

    def _decide(
        self,
        target: ApprovalState,
        *,
        actor: ActorReference | None = None,
        at: datetime | None,
        reason: str | None = None,
    ) -> Approval:
        require_transition("Approval", self.state, target, _APPROVAL_TRANSITIONS)
        normalized_reason = reason.strip() if reason else None
        if target is ApprovalState.REJECTED and not normalized_reason:
            raise DomainInvariantError("Rejected approvals require a reason")
        when = at or utc_now()
        if (
            target in {ApprovalState.APPROVED, ApprovalState.REJECTED}
            and when >= self.expires_at
        ):
            raise DomainInvariantError("Expired approval requests cannot be decided")
        if target is ApprovalState.EXPIRED and when < self.expires_at:
            raise DomainInvariantError("Approval cannot expire before expires_at")
        return replace(
            self,
            state=target,
            decided_by=actor,
            decided_at=when,
            reason=normalized_reason,
            updated_at=when,
            state_version=self.state_version + 1,
        )


def action_parameters_to_dict(parameters: ActionParameters) -> dict[str, object]:
    if isinstance(parameters, ManualInvestigationParameters):
        return {"schema_version": 1, "instruction": parameters.instruction}
    if isinstance(parameters, ScaleWorkloadParameters):
        return {
            "schema_version": 1,
            "desired_count": parameters.desired_count,
            "direction": parameters.direction.value if parameters.direction else None,
            "delta": parameters.delta,
        }
    if isinstance(parameters, RollbackDeploymentParameters):
        return {"schema_version": 1, "target_revision": parameters.target_revision}
    return {"schema_version": 1}


def action_parameters_from_dict(
    proposal_type: ActionProposalType, values: dict[str, object]
) -> ActionParameters:
    if values.get("schema_version") != 1:
        raise DomainInvariantError("Unsupported action parameter schema version")
    if proposal_type is ActionProposalType.MANUAL_INVESTIGATION:
        return ManualInvestigationParameters(str(values.get("instruction") or ""))
    if proposal_type is ActionProposalType.ACKNOWLEDGE_INCIDENT:
        return AcknowledgeIncidentParameters()
    if proposal_type is ActionProposalType.RESTART_WORKLOAD:
        return RestartWorkloadParameters()
    if proposal_type is ActionProposalType.SCALE_WORKLOAD:
        direction = values.get("direction")
        return ScaleWorkloadParameters(
            desired_count=(
                int(values["desired_count"])
                if values.get("desired_count") is not None
                else None
            ),
            direction=ScaleDirection(str(direction)) if direction else None,
            delta=int(values["delta"]) if values.get("delta") is not None else None,
        )
    if proposal_type is ActionProposalType.ROLLBACK_DEPLOYMENT:
        revision = values.get("target_revision")
        return RollbackDeploymentParameters(
            str(revision) if revision is not None else None
        )
    raise DomainInvariantError("Unsupported action proposal type")
