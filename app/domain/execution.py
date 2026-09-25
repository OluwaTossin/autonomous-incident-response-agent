"""Immutable, proposal-bound execution preparation domain."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from app.domain.actions import (
    AcknowledgeIncidentParameters,
    ActionParameters,
    ActionReference,
    ActionReversibility,
    ActionRiskLevel,
    ActionTarget,
    ActionTargetProvenance,
    ActionTargetType,
    Approval,
    ApprovalState,
    action_parameters_to_dict,
)
from app.domain.common import (
    ActorKind,
    ActorReference,
    DomainInvariantError,
    WorkspaceScope,
    require_aware,
    require_transition,
    validate_timestamps,
)
from app.domain.identifiers import ApprovalId, ExecutionIntentId
from app.domain.incidents import IncidentReference, TriageRunReference


class ConnectorKind(StrEnum):
    INTERNAL = "internal"


class OperationKind(StrEnum):
    ACKNOWLEDGE_INCIDENT = "acknowledge_incident"


class ExecutionIntentState(StrEnum):
    PREPARED = "prepared"
    INVALIDATED = "invalidated"
    CANCELLED = "cancelled"


_TRANSITIONS = {
    ExecutionIntentState.PREPARED: frozenset(
        {ExecutionIntentState.INVALIDATED, ExecutionIntentState.CANCELLED}
    ),
    ExecutionIntentState.INVALIDATED: frozenset(),
    ExecutionIntentState.CANCELLED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class ExecutionIntent:
    id: ExecutionIntentId
    scope: WorkspaceScope
    incident: IncidentReference
    triage_run: TriageRunReference
    action: ActionReference
    approval_id: ApprovalId
    proposal_schema_version: int
    source_result_version: int
    source_result_hash: str
    normalized_action_hash: str
    approval_state_version: int
    approval_binding_hash: str
    approved_by: ActorReference
    approved_at: datetime
    connector_kind: ConnectorKind
    operation_kind: OperationKind
    provider: str
    target: ActionTarget
    parameters: ActionParameters
    request_schema_version: int
    risk_level: ActionRiskLevel
    reversibility: ActionReversibility
    policy_version: int
    lifecycle_state: ExecutionIntentState
    intent_hash: str
    created_by: ActorReference
    created_at: datetime
    updated_at: datetime
    execute_before: datetime
    state_version: int = 1
    terminal_at: datetime | None = None
    terminal_reason: str | None = None

    def __post_init__(self) -> None:
        if not (
            self.scope
            == self.incident.scope
            == self.triage_run.scope
            == self.action.scope
        ):
            raise DomainInvariantError("Execution intent references must share scope")
        if self.approved_by.kind is not ActorKind.HUMAN:
            raise DomainInvariantError("Execution intent requires a human approval")
        if self.proposal_schema_version != 1 or self.source_result_version < 1:
            raise DomainInvariantError("Execution intent proposal binding is invalid")
        if self.approval_state_version < 2:
            raise DomainInvariantError("Execution intent approval version is invalid")
        if self.request_schema_version != 1 or self.policy_version != 1:
            raise DomainInvariantError("Execution intent schema version is invalid")
        if self.state_version < 1:
            raise DomainInvariantError("Execution intent state version is invalid")
        for name, value in (
            ("source_result_hash", self.source_result_hash),
            ("normalized_action_hash", self.normalized_action_hash),
            ("approval_binding_hash", self.approval_binding_hash),
        ):
            if not _is_sha256(value):
                raise DomainInvariantError(f"Execution intent {name} is invalid")
        require_aware(self.approved_at, "approved_at")
        require_aware(self.execute_before, "execute_before")
        validate_timestamps(self.created_at, self.updated_at)
        if self.created_at < self.approved_at:
            raise DomainInvariantError("Execution intent cannot precede approval")
        if self.execute_before <= self.created_at:
            raise DomainInvariantError("Execution deadline must follow preparation")
        if self.terminal_at is not None:
            require_aware(self.terminal_at, "terminal_at")
            if self.terminal_at < self.created_at:
                raise DomainInvariantError(
                    "Intent terminal time cannot precede creation"
                )
        if self.lifecycle_state is ExecutionIntentState.PREPARED:
            if self.terminal_at is not None or self.terminal_reason is not None:
                raise DomainInvariantError(
                    "Prepared intent cannot carry terminal fields"
                )
        elif self.terminal_at is None or not self.terminal_reason:
            raise DomainInvariantError("Terminal intent requires time and reason")
        if self.terminal_reason is not None:
            reason = self.terminal_reason.strip()
            if not reason or len(reason) > 500:
                raise DomainInvariantError("Intent terminal reason is invalid")
            object.__setattr__(self, "terminal_reason", reason)
        provider = self.provider.strip().lower()
        if (
            provider != "aira"
            or self.connector_kind is not ConnectorKind.INTERNAL
            or self.operation_kind is not OperationKind.ACKNOWLEDGE_INCIDENT
        ):
            raise DomainInvariantError("Unsupported execution connector")
        if (
            self.target.type is not ActionTargetType.INCIDENT
            or self.target.identifier != str(self.incident.id)
            or self.target.provider != "aira"
            or self.target.provenance is not ActionTargetProvenance.INCIDENT
            or self.target.integration_id is not None
            or self.target.account_id is not None
            or self.target.region is not None
        ):
            raise DomainInvariantError("Execution intent target is not authoritative")
        if not isinstance(self.parameters, AcknowledgeIncidentParameters):
            raise DomainInvariantError(
                "Execution intent parameters are not allowlisted"
            )
        object.__setattr__(self, "provider", provider)
        expected_hash = canonical_intent_hash(self)
        if not self.intent_hash:
            object.__setattr__(self, "intent_hash", expected_hash)
        elif not _is_sha256(self.intent_hash) or self.intent_hash != expected_hash:
            raise DomainInvariantError(
                "Execution intent hash does not match its contents"
            )

    def invalidate(self, *, at: datetime, reason: str) -> ExecutionIntent:
        return self._terminate(ExecutionIntentState.INVALIDATED, at, reason)

    def cancel(self, *, at: datetime, reason: str) -> ExecutionIntent:
        return self._terminate(ExecutionIntentState.CANCELLED, at, reason)

    def _terminate(
        self, target: ExecutionIntentState, at: datetime, reason: str
    ) -> ExecutionIntent:
        require_transition(
            "ExecutionIntent", self.lifecycle_state, target, _TRANSITIONS
        )
        return replace(
            self,
            lifecycle_state=target,
            terminal_at=at,
            terminal_reason=reason,
            updated_at=at,
            state_version=self.state_version + 1,
        )


def approval_binding_hash(approval: Approval) -> str:
    if (
        approval.state is not ApprovalState.APPROVED
        or approval.decided_by is None
        or approval.decided_at is None
    ):
        raise DomainInvariantError("Only approved human decisions can be fingerprinted")
    return _hash(
        {
            "approval_id": str(approval.id),
            "action_proposal_id": str(approval.action.id),
            "state": approval.state.value,
            "state_version": approval.state_version,
            "approved_by": _actor(approval.decided_by),
            "approved_at": approval.decided_at.isoformat(),
            "proposal_schema_version": approval.proposal_schema_version,
            "source_result_version": approval.source_result_version,
            "source_result_hash": approval.source_result_hash,
            "normalized_action_hash": approval.normalized_action_hash,
        }
    )


def canonical_intent_hash(intent: ExecutionIntent) -> str:
    return _hash(
        {
            "schema_version": intent.request_schema_version,
            "policy_version": intent.policy_version,
            "action_proposal_id": str(intent.action.id),
            "approval_id": str(intent.approval_id),
            "proposal_schema_version": intent.proposal_schema_version,
            "source_result_version": intent.source_result_version,
            "source_result_hash": intent.source_result_hash,
            "normalized_action_hash": intent.normalized_action_hash,
            "approval_state_version": intent.approval_state_version,
            "approval_binding_hash": intent.approval_binding_hash,
            "connector_kind": intent.connector_kind.value,
            "operation_kind": intent.operation_kind.value,
            "provider": intent.provider,
            "target": {
                "type": intent.target.type.value,
                "identifier": intent.target.identifier,
                "provider": intent.target.provider,
                "provenance": intent.target.provenance.value,
                "integration_id": (
                    str(intent.target.integration_id)
                    if intent.target.integration_id is not None
                    else None
                ),
                "account_id": intent.target.account_id,
                "region": intent.target.region,
            },
            "parameters": action_parameters_to_dict(intent.parameters),
            "risk_level": intent.risk_level.value,
            "reversibility": intent.reversibility.value,
            "approved_by": _actor(intent.approved_by),
            "approved_at": intent.approved_at.isoformat(),
            "execute_before": intent.execute_before.isoformat(),
        }
    )


def _actor(actor: ActorReference) -> dict[str, str | None]:
    return {
        "kind": actor.kind.value,
        "id": str(actor.actor_id) if actor.actor_id is not None else None,
        "system_name": actor.system_name,
    }


def _hash(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )
