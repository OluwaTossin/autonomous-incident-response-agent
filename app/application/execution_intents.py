"""Authorized immutable execution-intent preparation without provider execution."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol, Self

from app.auth.context import ActorContext
from app.authorization.permissions import Permission
from app.authorization.service import AuthorizationService, AuthorizedTenantContext
from app.domain.actions import (
    ActionPolicyStatus,
    ActionProposal,
    ActionProposalState,
    ActionReversibility,
    Approval,
    ApprovalState,
)
from app.domain.common import CorrelationContext, OrganizationScope
from app.domain.events import AuditEvent
from app.domain.execution import (
    ExecutionIntent,
    ExecutionIntentState,
    approval_binding_hash,
)
from app.domain.identifiers import (
    ActionId,
    ApprovalId,
    AuditEventId,
    CorrelationId,
    ExecutionIntentId,
    OrganizationId,
    WorkspaceId,
)
from app.domain.usage import QuotaType, UsageType
from app.integrations.action_connectors import (
    ActionConnectorRegistry,
    ConnectorValidationError,
)


class ExecutionIntentNotFound(LookupError):
    pass


class ExecutionIntentConflict(RuntimeError):
    pass


class IntentValidationCode(StrEnum):
    APPROVAL_INVALID = "approval_invalid"
    APPROVAL_TOO_OLD = "approval_too_old"
    PROPOSAL_STALE = "proposal_stale"
    POLICY_BLOCKED = "policy_blocked"
    UNSUPPORTED_ACTION = "unsupported_action"
    TARGET_NOT_AUTHORITATIVE = "target_not_authoritative"
    PARAMETERS_INVALID = "parameters_invalid"


class ExecutionIntentValidationError(ValueError):
    def __init__(self, code: IntentValidationCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class ExecutionIntentRepository(Protocol):
    def create_or_get(
        self, intent: ExecutionIntent
    ) -> tuple[ExecutionIntent, bool]: ...
    def get(
        self, intent_id: ExecutionIntentId, *, for_update: bool = False
    ) -> ExecutionIntent | None: ...
    def get_for_approval(
        self, approval_id: ApprovalId, *, for_update: bool = False
    ) -> ExecutionIntent | None: ...
    def list_for_proposal(
        self, proposal_id: ActionId, *, for_update: bool = False
    ) -> Sequence[ExecutionIntent]: ...
    def save_state(self, intent: ExecutionIntent, *, expected_version: int) -> None: ...


class ExecutionIntentUnitOfWork(Protocol):
    action_proposals: object
    approvals: object
    execution_intents: ExecutionIntentRepository
    audit_events: object

    def __enter__(self) -> Self: ...
    def __exit__(self, exc_type, exc_value, traceback) -> None: ...


ExecutionIntentUnitOfWorkFactory = Callable[
    [AuthorizedTenantContext], ExecutionIntentUnitOfWork
]


class ExecutionIntentObserver(Protocol):
    def record(
        self, event: str, connector: str, operation: str, result: str, risk: str
    ) -> None: ...


class NoopExecutionIntentObserver:
    def record(
        self, event: str, connector: str, operation: str, result: str, risk: str
    ) -> None:
        return None


class HostedExecutionIntentService:
    """Freezes approved actions and deliberately exposes no execution method."""

    def __init__(
        self,
        authorization: AuthorizationService,
        uow_factory: ExecutionIntentUnitOfWorkFactory,
        *,
        connectors: ActionConnectorRegistry = ActionConnectorRegistry(),
        approval_preparation_ttl: timedelta = timedelta(minutes=30),
        intent_lifetime: timedelta = timedelta(minutes=30),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        observer: ExecutionIntentObserver = NoopExecutionIntentObserver(),
        enforce_quotas: bool = False,
    ) -> None:
        for name, value in (
            ("Approval preparation TTL", approval_preparation_ttl),
            ("Intent lifetime", intent_lifetime),
        ):
            if not timedelta(minutes=1) <= value <= timedelta(hours=24):
                raise ValueError(f"{name} must be between one minute and 24 hours")
        self._authorization = authorization
        self._uow_factory = uow_factory
        self._connectors = connectors
        self._approval_preparation_ttl = approval_preparation_ttl
        self._intent_lifetime = intent_lifetime
        self._clock = clock
        self._observer = observer
        self._enforce_quotas = enforce_quotas

    def prepare(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        approval_id: ApprovalId,
    ) -> ExecutionIntent:
        context = self._authorization.authorize(
            actor,
            organization_id,
            Permission.EXECUTION_INTENT_PREPARE,
            workspace_id=workspace_id,
        )
        now = self._clock()
        rejected: ExecutionIntentValidationError | None = None
        observed: list[tuple[str, str, str, str, str]] = []
        result: ExecutionIntent | None = None
        with self._uow_factory(context) as uow:
            approval = uow.approvals.get(approval_id, for_update=True)
            if approval is None:
                raise ExecutionIntentNotFound("Approval not found")
            proposal = uow.action_proposals.get(approval.action.id, for_update=True)
            if proposal is None:
                raise ExecutionIntentNotFound("Approved action proposal not found")
            existing = uow.execution_intents.get_for_approval(
                approval_id, for_update=True
            )
            if existing is not None:
                result = self._invalidate_if_needed(
                    uow, context, existing, proposal, approval, now
                )
            else:
                try:
                    prepared = self._prepare_operation(proposal, approval, now)
                except ExecutionIntentValidationError as exc:
                    rejected = exc
                    uow.audit_events.add(
                        _rejection_audit(context, proposal, approval, exc, now)
                    )
                    if exc.code in {
                        IntentValidationCode.UNSUPPORTED_ACTION,
                        IntentValidationCode.TARGET_NOT_AUTHORITATIVE,
                        IntentValidationCode.PARAMETERS_INVALID,
                    }:
                        uow.audit_events.add(
                            _connector_rejection_audit(
                                context, proposal, approval, exc, now
                            )
                        )
                    observed.append(
                        (
                            "execution_intent_validation",
                            "none",
                            proposal.proposal_type.value,
                            exc.code.value,
                            proposal.risk_level.value,
                        )
                    )
                else:
                    if self._enforce_quotas:
                        uow.usage.decision(
                            QuotaType.EXECUTION_INTENTS_PER_HOUR, 1, at=now
                        )
                    result = ExecutionIntent(
                        id=ExecutionIntentId.new(),
                        scope=proposal.scope,
                        incident=proposal.incident,
                        triage_run=proposal.triage_run,
                        action=proposal.reference,
                        approval_id=approval.id,
                        proposal_schema_version=proposal.proposal_schema_version,
                        source_result_version=proposal.source_result_version,
                        source_result_hash=proposal.source_result_hash,
                        normalized_action_hash=proposal.normalized_action_hash,
                        approval_state_version=approval.state_version,
                        approval_binding_hash=approval_binding_hash(approval),
                        approved_by=approval.decided_by,
                        approved_at=approval.decided_at,
                        connector_kind=prepared.connector_kind,
                        operation_kind=prepared.operation_kind,
                        provider=prepared.provider,
                        target=proposal.target,
                        parameters=proposal.parameters,
                        request_schema_version=prepared.request_schema_version,
                        risk_level=proposal.risk_level,
                        reversibility=proposal.reversibility,
                        policy_version=1,
                        lifecycle_state=ExecutionIntentState.PREPARED,
                        intent_hash="",
                        created_by=context.actor,
                        created_at=now,
                        updated_at=now,
                        execute_before=now + self._intent_lifetime,
                    )
                    result, created = uow.execution_intents.create_or_get(result)
                    if created:
                        if self._enforce_quotas:
                            uow.usage.record(
                                UsageType.EXECUTION_INTENT_PREPARED,
                                1,
                                source="execution_intent",
                                source_reference=str(result.id),
                                correlation=CorrelationContext(CorrelationId.new()),
                                actor=context.actor,
                                at=now,
                                resource_type="execution_intent",
                                resource_id=str(result.id),
                            )
                        uow.audit_events.add(
                            _connector_audit(context, result, "passed")
                        )
                        uow.audit_events.add(_intent_audit(context, result, "prepared"))
                        observed.extend(
                            (
                                (
                                    "execution_intent_validation",
                                    result.connector_kind.value,
                                    result.operation_kind.value,
                                    "passed",
                                    result.risk_level.value,
                                ),
                                (
                                    "execution_intents_prepared",
                                    result.connector_kind.value,
                                    result.operation_kind.value,
                                    "prepared",
                                    result.risk_level.value,
                                ),
                            )
                        )
        for observation in observed:
            self._observer.record(*observation)
        if rejected is not None:
            raise rejected
        if result is None:
            raise RuntimeError("Execution intent preparation produced no result")
        return result

    def get(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        intent_id: ExecutionIntentId,
    ) -> ExecutionIntent:
        context = self._read_context(actor, organization_id, workspace_id)
        now = self._clock()
        with self._uow_factory(context) as uow:
            intent = uow.execution_intents.get(intent_id, for_update=True)
            if intent is None:
                raise ExecutionIntentNotFound("Execution intent not found")
            proposal = uow.action_proposals.get(intent.action.id)
            approval = uow.approvals.get(intent.approval_id)
            if proposal is None or approval is None:
                raise ExecutionIntentNotFound("Execution intent source not found")
            return self._invalidate_if_needed(
                uow, context, intent, proposal, approval, now
            )

    def list_for_proposal(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        proposal_id: ActionId,
    ) -> tuple[ExecutionIntent, ...]:
        context = self._read_context(actor, organization_id, workspace_id)
        now = self._clock()
        with self._uow_factory(context) as uow:
            proposal = uow.action_proposals.get(proposal_id)
            if proposal is None:
                raise ExecutionIntentNotFound("Action proposal not found")
            values = []
            for intent in uow.execution_intents.list_for_proposal(
                proposal_id, for_update=True
            ):
                approval = uow.approvals.get(intent.approval_id)
                if approval is None:
                    continue
                values.append(
                    self._invalidate_if_needed(
                        uow, context, intent, proposal, approval, now
                    )
                )
            return tuple(values)

    def cancel(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        intent_id: ExecutionIntentId,
        *,
        reason: str,
    ) -> ExecutionIntent:
        context = self._authorization.authorize(
            actor,
            organization_id,
            Permission.EXECUTION_INTENT_CANCEL,
            workspace_id=workspace_id,
        )
        now = self._clock()
        with self._uow_factory(context) as uow:
            current = uow.execution_intents.get(intent_id, for_update=True)
            if current is None:
                raise ExecutionIntentNotFound("Execution intent not found")
            if current.lifecycle_state is not ExecutionIntentState.PREPARED:
                raise ExecutionIntentConflict("Execution intent is already terminal")
            updated = current.cancel(at=now, reason=reason)
            uow.execution_intents.save_state(
                updated, expected_version=current.state_version
            )
            uow.audit_events.add(_intent_audit(context, updated, "cancelled"))
        self._observer.record(
            "execution_intents_cancelled",
            updated.connector_kind.value,
            updated.operation_kind.value,
            "cancelled",
            updated.risk_level.value,
        )
        return updated

    def _prepare_operation(
        self, proposal: ActionProposal, approval: Approval, now: datetime
    ):
        if approval.state is not ApprovalState.APPROVED or not approval.binds(proposal):
            raise ExecutionIntentValidationError(
                IntentValidationCode.APPROVAL_INVALID,
                "Approval does not authorize this exact action proposal",
            )
        if approval.decided_at is None or approval.decided_by is None:
            raise ExecutionIntentValidationError(
                IntentValidationCode.APPROVAL_INVALID,
                "Approval attribution is incomplete",
            )
        if now >= approval.decided_at + self._approval_preparation_ttl:
            raise ExecutionIntentValidationError(
                IntentValidationCode.APPROVAL_TOO_OLD,
                "Approval is outside the intent preparation window",
            )
        if proposal.lifecycle_state is not ActionProposalState.READY_FOR_REVIEW:
            raise ExecutionIntentValidationError(
                IntentValidationCode.PROPOSAL_STALE,
                "Action proposal is stale or no longer reviewable",
            )
        if (
            proposal.policy_status is not ActionPolicyStatus.ALLOWED_FOR_REVIEW
            or proposal.reversibility is ActionReversibility.IRREVERSIBLE
        ):
            raise ExecutionIntentValidationError(
                IntentValidationCode.POLICY_BLOCKED,
                "Current action policy does not permit preparation",
            )
        try:
            return self._connectors.prepare(proposal)
        except ConnectorValidationError as exc:
            code = IntentValidationCode(exc.code.value)
            raise ExecutionIntentValidationError(code, str(exc)) from exc

    def _invalidate_if_needed(
        self, uow, context, intent, proposal, approval, now
    ) -> ExecutionIntent:
        reason = _invalidation_reason(intent, proposal, approval, now)
        if (
            reason is None
            or intent.lifecycle_state is not ExecutionIntentState.PREPARED
        ):
            return intent
        updated = intent.invalidate(at=now, reason=reason)
        uow.execution_intents.save_state(updated, expected_version=intent.state_version)
        uow.audit_events.add(_intent_audit(context, updated, "invalidated"))
        self._observer.record(
            "execution_intents_invalidated",
            updated.connector_kind.value,
            updated.operation_kind.value,
            "invalidated",
            updated.risk_level.value,
        )
        return updated

    def _read_context(self, actor, organization_id, workspace_id):
        return self._authorization.authorize(
            actor,
            organization_id,
            Permission.EXECUTION_INTENT_READ,
            workspace_id=workspace_id,
        )


def _invalidation_reason(intent, proposal, approval, now) -> str | None:
    if now >= intent.execute_before:
        return "Execution deadline elapsed"
    if approval.state is not ApprovalState.APPROVED or not approval.binds(proposal):
        return "Approval no longer binds the exact proposal"
    if approval_binding_hash(approval) != intent.approval_binding_hash:
        return "Approval binding changed"
    if (
        proposal.lifecycle_state is not ActionProposalState.READY_FOR_REVIEW
        or proposal.policy_status is not ActionPolicyStatus.ALLOWED_FOR_REVIEW
        or proposal.source_result_hash != intent.source_result_hash
        or proposal.normalized_action_hash != intent.normalized_action_hash
        or proposal.target != intent.target
        or proposal.parameters != intent.parameters
    ):
        return "Action proposal changed or became ineligible"
    return None


def _intent_audit(context, intent: ExecutionIntent, outcome: str) -> AuditEvent:
    return AuditEvent(
        id=AuditEventId.new(),
        organization_scope=OrganizationScope(intent.scope.organization_id),
        workspace_scope=intent.scope,
        event_type=f"execution_intent.{outcome}",
        target_type="execution_intent",
        target_id=str(intent.id),
        actor=context.actor,
        occurred_at=intent.updated_at,
        correlation=CorrelationContext(
            CorrelationId.new(),
            incident_id=intent.incident.id,
            triage_run_id=intent.triage_run.id,
        ),
        details=(
            ("proposal_id", str(intent.action.id)),
            ("approval_id", str(intent.approval_id)),
            ("intent_hash", intent.intent_hash),
            ("connector", intent.connector_kind.value),
            ("operation", intent.operation_kind.value),
            ("risk", intent.risk_level.value),
            ("target_hash", _safe_target_hash(intent.target.identifier)),
            ("outcome", outcome),
        ),
    )


def _rejection_audit(context, proposal, approval, error, at) -> AuditEvent:
    return AuditEvent(
        id=AuditEventId.new(),
        organization_scope=OrganizationScope(proposal.scope.organization_id),
        workspace_scope=proposal.scope,
        event_type="execution_intent.preparation_rejected",
        target_type="approval",
        target_id=str(approval.id),
        actor=context.actor,
        occurred_at=at,
        correlation=CorrelationContext(
            CorrelationId.new(),
            incident_id=proposal.incident.id,
            triage_run_id=proposal.triage_run.id,
        ),
        details=(
            ("proposal_id", str(proposal.id)),
            ("approval_id", str(approval.id)),
            ("reason_code", error.code.value),
            ("risk", proposal.risk_level.value),
            ("target_hash", _safe_target_hash(proposal.target.identifier)),
        ),
    )


def _connector_rejection_audit(context, proposal, approval, error, at) -> AuditEvent:
    return AuditEvent(
        id=AuditEventId.new(),
        organization_scope=OrganizationScope(proposal.scope.organization_id),
        workspace_scope=proposal.scope,
        event_type="execution_intent.connector_validation_failed",
        target_type="approval",
        target_id=str(approval.id),
        actor=context.actor,
        occurred_at=at,
        correlation=CorrelationContext(
            CorrelationId.new(),
            incident_id=proposal.incident.id,
            triage_run_id=proposal.triage_run.id,
        ),
        details=(
            ("proposal_id", str(proposal.id)),
            ("approval_id", str(approval.id)),
            ("operation", proposal.proposal_type.value),
            ("risk", proposal.risk_level.value),
            ("target_hash", _safe_target_hash(proposal.target.identifier)),
            ("reason_code", error.code.value),
        ),
    )


def _connector_audit(context, intent: ExecutionIntent, outcome: str) -> AuditEvent:
    return AuditEvent(
        id=AuditEventId.new(),
        organization_scope=OrganizationScope(intent.scope.organization_id),
        workspace_scope=intent.scope,
        event_type=f"execution_intent.connector_validation_{outcome}",
        target_type="execution_intent",
        target_id=str(intent.id),
        actor=context.actor,
        occurred_at=intent.created_at,
        correlation=CorrelationContext(
            CorrelationId.new(),
            incident_id=intent.incident.id,
            triage_run_id=intent.triage_run.id,
        ),
        details=(
            ("proposal_id", str(intent.action.id)),
            ("approval_id", str(intent.approval_id)),
            ("connector", intent.connector_kind.value),
            ("operation", intent.operation_kind.value),
            ("risk", intent.risk_level.value),
            ("target_hash", _safe_target_hash(intent.target.identifier)),
            ("outcome", outcome),
        ),
    )


def _safe_target_hash(identifier: str) -> str:
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()
