"""Transport-neutral, proposal-bound human approval workflow."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Protocol, Self

from app.auth.context import ActorContext
from app.authorization.permissions import Permission
from app.authorization.service import (
    AuthorizationDenied,
    AuthorizationService,
    AuthorizedTenantContext,
)
from app.domain.actions import (
    APPROVAL_TERMINAL_STATES,
    ActionPolicyStatus,
    ActionProposal,
    ActionProposalState,
    ActionReversibility,
    Approval,
    ApprovalState,
)
from app.domain.common import ActorKind, CorrelationContext, OrganizationScope
from app.domain.events import AuditEvent
from app.domain.identifiers import (
    ActionId,
    ApprovalId,
    AuditEventId,
    CorrelationId,
    OrganizationId,
    WorkspaceId,
)


class ApprovalNotFound(LookupError):
    pass


class ApprovalConflict(RuntimeError):
    pass


class ApprovalEligibilityError(ValueError):
    pass


class ApprovalRepository(Protocol):
    def create_or_get_active(self, approval: Approval) -> tuple[Approval, bool]: ...
    def get(
        self, approval_id: ApprovalId, *, for_update: bool = False
    ) -> Approval | None: ...
    def get_active_for_proposal(
        self, proposal_id: ActionId, *, for_update: bool = False
    ) -> Approval | None: ...
    def list_for_proposal(self, proposal_id: ActionId) -> Sequence[Approval]: ...
    def list_due(self, at: datetime, *, limit: int) -> Sequence[Approval]: ...
    def save(self, approval: Approval, *, expected_version: int) -> None: ...


class ApprovalUnitOfWork(Protocol):
    action_proposals: object
    approvals: ApprovalRepository
    audit_events: object

    def __enter__(self) -> Self: ...
    def __exit__(self, exc_type, exc_value, traceback) -> None: ...


ApprovalUnitOfWorkFactory = Callable[[AuthorizedTenantContext], ApprovalUnitOfWork]


class ApprovalObserver(Protocol):
    def record(
        self,
        event: str,
        outcome: str,
        risk_level: str,
        proposal_type: str,
        duration_ms: int = 0,
    ) -> None: ...


class NoopApprovalObserver:
    def record(
        self,
        event: str,
        outcome: str,
        risk_level: str,
        proposal_type: str,
        duration_ms: int = 0,
    ) -> None:
        return None


class HostedApprovalService:
    """Persists review decisions and deliberately has no execution capability."""

    def __init__(
        self,
        authorization: AuthorizationService,
        uow_factory: ApprovalUnitOfWorkFactory,
        *,
        approval_ttl: timedelta = timedelta(minutes=30),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        observer: ApprovalObserver = NoopApprovalObserver(),
    ) -> None:
        if not timedelta(minutes=1) <= approval_ttl <= timedelta(hours=24):
            raise ValueError("Approval TTL must be between one minute and 24 hours")
        self._authorization = authorization
        self._uow_factory = uow_factory
        self._approval_ttl = approval_ttl
        self._clock = clock
        self._observer = observer

    def request_approval(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        proposal_id: ActionId,
    ) -> Approval:
        self._require_human(actor)
        context = self._authorization.authorize(
            actor,
            organization_id,
            Permission.APPROVAL_REQUEST,
            workspace_id=workspace_id,
        )
        now = self._clock()
        observed: tuple[str, Approval, ActionProposal] | None = None
        with self._uow_factory(context) as uow:
            proposal = uow.action_proposals.get(proposal_id, for_update=True)
            if proposal is None:
                raise ApprovalNotFound("Action proposal not found")
            self._require_eligible(proposal)
            active = uow.approvals.get_active_for_proposal(proposal_id, for_update=True)
            if active is not None and now >= active.expires_at:
                expired = active.expire(at=now)
                uow.approvals.save(expired, expected_version=active.state_version)
                uow.audit_events.add(_audit(context.actor, proposal, expired))
                observed = ("approval_expired", expired, proposal)
                active = None
            if active is not None:
                return active
            requested = Approval.request(
                id=ApprovalId.new(),
                proposal=proposal,
                requested_by=context.actor,
                requested_at=now,
                expires_at=now + self._approval_ttl,
            )
            resolved, created = uow.approvals.create_or_get_active(requested)
            if created:
                uow.audit_events.add(_audit(context.actor, proposal, resolved))
                observed = ("approval_requested", resolved, proposal)
        if observed is not None:
            self._observe(*observed)
        return resolved

    def get_approval(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        approval_id: ApprovalId,
    ) -> Approval:
        context = self._read_context(actor, organization_id, workspace_id)
        now = self._clock()
        observed = None
        with self._uow_factory(context) as uow:
            current = uow.approvals.get(approval_id, for_update=True)
            if current is None:
                raise ApprovalNotFound("Approval not found")
            proposal = uow.action_proposals.get(current.action.id)
            if proposal is None:
                raise ApprovalNotFound("Approval proposal not found")
            current, observed = self._expire_if_due(
                uow, context.actor, proposal, current, now
            )
        if observed is not None:
            self._observe(*observed)
        return current

    def list_for_proposal(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        proposal_id: ActionId,
    ) -> tuple[Approval, ...]:
        context = self._read_context(actor, organization_id, workspace_id)
        self._expire_due_in_context(context, limit=100)
        with self._uow_factory(context) as uow:
            if uow.action_proposals.get(proposal_id) is None:
                raise ApprovalNotFound("Action proposal not found")
            return tuple(uow.approvals.list_for_proposal(proposal_id))

    def approve(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        approval_id: ApprovalId,
        *,
        reason: str | None = None,
    ) -> Approval:
        return self._decide(
            actor,
            organization_id,
            workspace_id,
            approval_id,
            ApprovalState.APPROVED,
            reason,
        )

    def reject(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        approval_id: ApprovalId,
        *,
        reason: str,
    ) -> Approval:
        return self._decide(
            actor,
            organization_id,
            workspace_id,
            approval_id,
            ApprovalState.REJECTED,
            reason,
        )

    def cancel(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        approval_id: ApprovalId,
        *,
        reason: str | None = None,
    ) -> Approval:
        self._require_human(actor)
        read_context = self._read_context(actor, organization_id, workspace_id)
        with self._uow_factory(read_context) as uow:
            snapshot = uow.approvals.get(approval_id)
        if snapshot is None:
            raise ApprovalNotFound("Approval not found")
        if actor.actor != snapshot.requested_by:
            context = self._authorization.authorize(
                actor,
                organization_id,
                Permission.APPROVAL_DECIDE,
                workspace_id=workspace_id,
            )
        else:
            context = read_context
        now = self._clock()
        observed = None
        with self._uow_factory(context) as uow:
            proposal = uow.action_proposals.get(snapshot.action.id, for_update=True)
            current = uow.approvals.get(approval_id, for_update=True)
            if current is None or proposal is None:
                raise ApprovalNotFound("Approval not found")
            if current.state in APPROVAL_TERMINAL_STATES:
                raise ApprovalConflict("Approval request is already terminal")
            if now >= current.expires_at:
                updated = current.expire(at=now)
            else:
                updated = current.cancel(context.actor, at=now, reason=reason)
            uow.approvals.save(updated, expected_version=current.state_version)
            uow.audit_events.add(_audit(context.actor, proposal, updated))
            observed = (_event_name(updated), updated, proposal)
        self._observe(*observed)
        return updated

    def expire_due(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        *,
        limit: int = 100,
    ) -> tuple[Approval, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("Expiry limit must be between 1 and 500")
        context = self._read_context(actor, organization_id, workspace_id)
        return self._expire_due_in_context(context, limit=limit)

    def _decide(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        approval_id: ApprovalId,
        target: ApprovalState,
        reason: str | None,
    ) -> Approval:
        self._require_human(actor)
        context = self._authorization.authorize(
            actor,
            organization_id,
            Permission.APPROVAL_DECIDE,
            workspace_id=workspace_id,
        )
        now = self._clock()
        terminal_conflict: str | None = None
        observed = None
        updated = None
        with self._uow_factory(context) as uow:
            snapshot = uow.approvals.get(approval_id)
            if snapshot is None:
                raise ApprovalNotFound("Approval not found")
            proposal = uow.action_proposals.get(snapshot.action.id, for_update=True)
            current = uow.approvals.get(approval_id, for_update=True)
            if current is None or proposal is None:
                raise ApprovalNotFound("Approval not found")
            if current.state in APPROVAL_TERMINAL_STATES:
                raise ApprovalConflict("Approval request is already terminal")
            if now >= current.expires_at:
                updated = current.expire(at=now)
                terminal_conflict = "Approval request has expired"
            elif not current.binds(proposal) or not _is_eligible(proposal):
                updated = current.cancel(
                    context.actor,
                    at=now,
                    reason="Proposal is no longer eligible for approval",
                )
                terminal_conflict = "Action proposal is stale or no longer eligible"
            elif current.requested_by == context.actor:
                raise ApprovalConflict(
                    "Approval requester cannot decide their own request"
                )
            elif target is ApprovalState.APPROVED:
                updated = current.approve(context.actor, at=now, reason=reason)
            else:
                updated = current.reject(context.actor, reason or "", at=now)
            uow.approvals.save(updated, expected_version=current.state_version)
            uow.audit_events.add(_audit(context.actor, proposal, updated))
            observed = (_event_name(updated), updated, proposal)
        self._observe(*observed)
        if terminal_conflict is not None:
            raise ApprovalConflict(terminal_conflict)
        return updated

    def _expire_due_in_context(self, context, *, limit: int) -> tuple[Approval, ...]:
        now = self._clock()
        expired: list[tuple[Approval, ActionProposal]] = []
        with self._uow_factory(context) as uow:
            for current in uow.approvals.list_due(now, limit=limit):
                proposal = uow.action_proposals.get(current.action.id)
                if proposal is None:
                    continue
                updated = current.expire(at=now)
                uow.approvals.save(updated, expected_version=current.state_version)
                uow.audit_events.add(_audit(context.actor, proposal, updated))
                expired.append((updated, proposal))
        for approval, proposal in expired:
            self._observe("approval_expired", approval, proposal)
        return tuple(item[0] for item in expired)

    @staticmethod
    def _expire_if_due(uow, actor, proposal, approval, now):
        if approval.state is not ApprovalState.REQUESTED or now < approval.expires_at:
            return approval, None
        updated = approval.expire(at=now)
        uow.approvals.save(updated, expected_version=approval.state_version)
        uow.audit_events.add(_audit(actor, proposal, updated))
        return updated, ("approval_expired", updated, proposal)

    @staticmethod
    def _require_human(actor: ActorContext) -> None:
        if actor.actor.kind is not ActorKind.HUMAN:
            raise AuthorizationDenied("Approval operations require a human actor")

    @staticmethod
    def _require_eligible(proposal: ActionProposal) -> None:
        if not _is_eligible(proposal):
            raise ApprovalEligibilityError(
                "Action proposal is not eligible for approval"
            )

    def _read_context(self, actor, organization_id, workspace_id):
        return self._authorization.authorize(
            actor,
            organization_id,
            Permission.APPROVAL_READ,
            workspace_id=workspace_id,
        )

    def _observe(
        self, event: str, approval: Approval, proposal: ActionProposal
    ) -> None:
        duration_ms = (
            max(
                0,
                int(
                    (approval.decided_at - approval.requested_at).total_seconds() * 1000
                ),
            )
            if approval.decided_at is not None
            else 0
        )
        self._observer.record(
            event,
            approval.state.value,
            proposal.risk_level.value,
            proposal.proposal_type.value,
            duration_ms,
        )


def _is_eligible(proposal: ActionProposal) -> bool:
    return (
        proposal.lifecycle_state is ActionProposalState.READY_FOR_REVIEW
        and proposal.policy_status is ActionPolicyStatus.ALLOWED_FOR_REVIEW
        and proposal.reversibility is not ActionReversibility.IRREVERSIBLE
    )


def _event_name(approval: Approval) -> str:
    return {
        ApprovalState.REQUESTED: "approval_requested",
        ApprovalState.APPROVED: "approval_approved",
        ApprovalState.REJECTED: "approval_rejected",
        ApprovalState.EXPIRED: "approval_expired",
        ApprovalState.CANCELLED: "approval_cancelled",
    }[approval.state]


def _audit(actor, proposal: ActionProposal, approval: Approval) -> AuditEvent:
    return AuditEvent(
        id=AuditEventId.new(),
        organization_scope=OrganizationScope(approval.scope.organization_id),
        workspace_scope=approval.scope,
        event_type=f"approval.{approval.state.value}",
        target_type="approval",
        target_id=str(approval.id),
        actor=actor,
        occurred_at=approval.updated_at,
        correlation=CorrelationContext(
            CorrelationId.new(),
            incident_id=proposal.incident.id,
            triage_run_id=proposal.triage_run.id,
        ),
        details=(
            ("proposal_id", str(proposal.id)),
            ("incident_id", str(proposal.incident.id)),
            ("triage_run_id", str(proposal.triage_run.id)),
            ("state", approval.state.value),
            ("risk_level", proposal.risk_level.value),
            ("proposal_type", proposal.proposal_type.value),
            ("proposal_schema_version", str(approval.proposal_schema_version)),
            ("source_result_hash", approval.source_result_hash),
            ("normalized_action_hash", approval.normalized_action_hash),
        ),
    )
