"""Controlled action and human approval domain models."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

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
from app.domain.identifiers import ActionId, ApprovalId
from app.domain.incidents import IncidentReference, TriageRunReference


class ActionRisk(StrEnum):
    INFORMATIONAL = "informational"
    CONSEQUENTIAL = "consequential"


class ActionState(StrEnum):
    PROPOSED = "proposed"
    AWAITING_APPROVAL = "awaiting_approval"
    READY = "ready"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ApprovalState(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


_ACTION_TRANSITIONS = {
    ActionState.PROPOSED: frozenset(
        {ActionState.AWAITING_APPROVAL, ActionState.READY, ActionState.CANCELLED}
    ),
    ActionState.AWAITING_APPROVAL: frozenset(
        {ActionState.READY, ActionState.REJECTED, ActionState.EXPIRED, ActionState.CANCELLED}
    ),
    ActionState.READY: frozenset(
        {ActionState.EXECUTING, ActionState.EXPIRED, ActionState.CANCELLED}
    ),
    ActionState.EXECUTING: frozenset({ActionState.SUCCEEDED, ActionState.FAILED}),
    ActionState.SUCCEEDED: frozenset(),
    ActionState.FAILED: frozenset(),
    ActionState.REJECTED: frozenset(),
    ActionState.EXPIRED: frozenset(),
    ActionState.CANCELLED: frozenset(),
}

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

ACTION_TERMINAL_STATES = frozenset(
    {
        ActionState.SUCCEEDED,
        ActionState.FAILED,
        ActionState.REJECTED,
        ActionState.EXPIRED,
        ActionState.CANCELLED,
    }
)
APPROVAL_TERMINAL_STATES = frozenset(
    {
        ApprovalState.APPROVED,
        ApprovalState.REJECTED,
        ApprovalState.EXPIRED,
        ApprovalState.CANCELLED,
    }
)


@dataclass(frozen=True, slots=True)
class ActionReference:
    id: ActionId
    scope: WorkspaceScope


@dataclass(frozen=True, slots=True)
class Approval:
    id: ApprovalId
    scope: WorkspaceScope
    action: ActionReference
    state: ApprovalState
    requested_by: ActorReference
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    decided_by: ActorReference | None = None
    decided_at: datetime | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.scope != self.action.scope:
            raise DomainInvariantError("Approval and Action must have the same workspace scope")
        validate_timestamps(self.created_at, self.updated_at)
        require_aware(self.expires_at, "expires_at")
        if self.expires_at <= self.created_at:
            raise DomainInvariantError("Approval expires_at must follow created_at")
        if self.decided_at is not None:
            require_aware(self.decided_at, "decided_at")
            if self.decided_at < self.created_at:
                raise DomainInvariantError("Approval decided_at cannot precede created_at")
        terminal = self.state in APPROVAL_TERMINAL_STATES
        if terminal and self.decided_at is None:
            raise DomainInvariantError("Terminal approvals require decided_at")
        if self.state in {ApprovalState.APPROVED, ApprovalState.REJECTED} and self.decided_by is None:
            raise DomainInvariantError("Approved or rejected approvals require decided_by")
        if (
            self.state is ApprovalState.APPROVED
            and self.decided_by is not None
            and self.decided_by.kind is not ActorKind.HUMAN
        ):
            raise DomainInvariantError("Consequential action approval requires a human actor")
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
        if not terminal and any((self.decided_by, self.decided_at, self.reason)):
            raise DomainInvariantError("Requested approvals cannot carry decision fields")

    def approve(self, actor: ActorReference, *, at: datetime | None = None) -> Approval:
        return self._decide(ApprovalState.APPROVED, actor=actor, at=at)

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

    def cancel(self, *, at: datetime | None = None) -> Approval:
        return self._decide(ApprovalState.CANCELLED, at=at)

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
        if target in {ApprovalState.APPROVED, ApprovalState.REJECTED} and when >= self.expires_at:
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
        )


@dataclass(frozen=True, slots=True)
class ActionProposal:
    id: ActionId
    scope: WorkspaceScope
    action_type: str
    target: str
    parameters: tuple[tuple[str, str], ...]
    risk: ActionRisk
    state: ActionState
    proposed_by: ActorReference
    created_at: datetime
    updated_at: datetime
    incident: IncidentReference | None = None
    triage_run: TriageRunReference | None = None
    completed_at: datetime | None = None
    outcome_reference: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if not self.action_type.strip() or not self.target.strip():
            raise DomainInvariantError("Action action_type and target cannot be blank")
        parameter_keys = [key.strip() for key, value in self.parameters if key.strip() and value.strip()]
        if len(parameter_keys) != len(self.parameters) or len(set(parameter_keys)) != len(parameter_keys):
            raise DomainInvariantError("Action parameters require unique non-blank keys and values")
        if self.incident is not None and self.incident.scope != self.scope:
            raise DomainInvariantError("Action and Incident must have the same workspace scope")
        if self.triage_run is not None and self.triage_run.scope != self.scope:
            raise DomainInvariantError("Action and TriageRun must have the same workspace scope")
        validate_timestamps(self.created_at, self.updated_at)
        if self.completed_at is not None:
            require_aware(self.completed_at, "completed_at")
            if self.completed_at < self.created_at:
                raise DomainInvariantError("Action completed_at cannot precede created_at")
        if self.state in ACTION_TERMINAL_STATES and self.completed_at is None:
            raise DomainInvariantError("Terminal actions require completed_at")
        if self.state not in ACTION_TERMINAL_STATES and self.completed_at is not None:
            raise DomainInvariantError("Non-terminal actions cannot have completed_at")
        if self.state is ActionState.FAILED and not self.error_message:
            raise DomainInvariantError("Failed actions require error_message")
        if self.state is not ActionState.FAILED and self.error_message is not None:
            raise DomainInvariantError("Only failed actions may carry error_message")
        if self.state is ActionState.SUCCEEDED and not self.outcome_reference:
            raise DomainInvariantError("Succeeded actions require outcome_reference")
        if self.state is not ActionState.SUCCEEDED and self.outcome_reference is not None:
            raise DomainInvariantError("Only succeeded actions may carry outcome_reference")

    @property
    def reference(self) -> ActionReference:
        return ActionReference(self.id, self.scope)

    def request_approval(self, *, at: datetime | None = None) -> ActionProposal:
        if self.risk is not ActionRisk.CONSEQUENTIAL:
            raise DomainInvariantError("Only consequential actions require approval")
        return self._transition(ActionState.AWAITING_APPROVAL, at=at)

    def mark_ready(
        self,
        *,
        approval: Approval | None = None,
        at: datetime | None = None,
    ) -> ActionProposal:
        if self.risk is ActionRisk.CONSEQUENTIAL:
            if approval is None or approval.state is not ApprovalState.APPROVED:
                raise DomainInvariantError("Consequential actions require an approved approval")
            if approval.action != self.reference:
                raise DomainInvariantError("Approval does not authorize this action")
        elif approval is not None:
            raise DomainInvariantError("Informational actions do not consume approvals")
        return self._transition(ActionState.READY, at=at)

    def begin_execution(self, *, at: datetime | None = None) -> ActionProposal:
        return self._transition(ActionState.EXECUTING, at=at)

    def succeed(self, outcome_reference: str, *, at: datetime | None = None) -> ActionProposal:
        normalized = outcome_reference.strip()
        if not normalized:
            raise DomainInvariantError("Successful actions require an outcome reference")
        return self._transition(
            ActionState.SUCCEEDED,
            at=at,
            outcome_reference=normalized,
        )

    def fail(self, error: str, *, at: datetime | None = None) -> ActionProposal:
        normalized = error.strip()
        if not normalized:
            raise DomainInvariantError("Failed actions require an error")
        return self._transition(ActionState.FAILED, at=at, error_message=normalized)

    def reject(self, *, at: datetime | None = None) -> ActionProposal:
        return self._transition(ActionState.REJECTED, at=at)

    def expire(self, *, at: datetime | None = None) -> ActionProposal:
        return self._transition(ActionState.EXPIRED, at=at)

    def cancel(self, *, at: datetime | None = None) -> ActionProposal:
        return self._transition(ActionState.CANCELLED, at=at)

    def _transition(
        self,
        target: ActionState,
        *,
        at: datetime | None,
        outcome_reference: str | None = None,
        error_message: str | None = None,
    ) -> ActionProposal:
        require_transition("ActionProposal", self.state, target, _ACTION_TRANSITIONS)
        when = at or utc_now()
        terminal_at = when if target in ACTION_TERMINAL_STATES else None
        return replace(
            self,
            state=target,
            completed_at=terminal_at,
            outcome_reference=outcome_reference,
            error_message=error_message,
            updated_at=when,
        )
