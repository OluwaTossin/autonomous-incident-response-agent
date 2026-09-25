"""Real PostgreSQL approval concurrency, proposal binding, and RLS evidence."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.approvals import ApprovalConflict, HostedApprovalService
from app.application.incidents import HostedIncidentInput
from app.application.triage_jobs import TriageCompletion
from app.auth.context import ActorContext, AuthenticationMethod
from app.authorization.service import AuthorizationService
from app.domain.common import ActorKind, ActorReference
from app.domain.identifiers import MembershipId, UserId
from app.domain.operations import JobResultReference
from app.domain.tenancy import (
    MembershipRole,
    MembershipState,
    OrganizationMembership,
    User,
)
from app.models.triage import TriageOutput
from app.persistence.postgres.authorization import (
    PostgresAuthorizationFactsRepository,
    PostgresTenantResourceValidator,
)
from app.persistence.postgres.incident_unit_of_work import (
    PostgresHostedIncidentUnitOfWork,
)
from app.persistence.postgres.mappers import membership_to_record, user_to_record
from app.persistence.postgres.models import (
    ActionProposalRecord,
    ApprovalRecord,
    AuditEventRecord,
)
from app.persistence.postgres.tenant import TenantContext, tenant_transaction
from app.worker.orchestration import JobHandlerOutcome

from .conftest import PostgresTestDatabase
from .test_document_persistence import _setup
from .test_incident_triage_persistence import _services, _worker
from .test_workspace_persistence import NOW


def _id(identifier_type, suffix: int):
    return identifier_type(f"00000000-0000-4000-8000-{suffix:012d}")


def _seed_admin(database, organization_id, suffix: int) -> ActorContext:
    user_id = _id(UserId, suffix)
    actor = ActorReference(ActorKind.HUMAN, actor_id=user_id)
    user = User(
        id=user_id,
        email=f"approver-{suffix}@example.com",
        display_name=f"Approver {suffix}",
        identity_provider="https://issuer.example",
        provider_subject=f"subject-{user_id}",
        created_at=NOW,
    )
    membership = OrganizationMembership(
        id=_id(MembershipId, suffix + 1000),
        organization_id=organization_id,
        user_id=user_id,
        role=MembershipRole.ADMIN,
        state=MembershipState.ACTIVE,
        created_by=actor,
        created_at=NOW,
        updated_at=NOW,
    )
    with Session(database.migration_engine) as session, session.begin():
        session.add(user_to_record(user))
        session.flush()
        session.add(membership_to_record(membership))
    return ActorContext(
        actor,
        AuthenticationMethod.OIDC,
        issuer="https://issuer.example",
        external_subject=f"subject-{user_id}",
    )


def _approval_service(runtime_session_factory, *, clock=lambda: NOW):
    authorization = AuthorizationService(
        PostgresAuthorizationFactsRepository(runtime_session_factory),
        PostgresTenantResourceValidator(runtime_session_factory),
    )
    return HostedApprovalService(
        authorization,
        lambda context: PostgresHostedIncidentUnitOfWork(
            runtime_session_factory, context
        ),
        clock=clock,
    )


def _completed_proposal(
    postgres_database,
    runtime_session_factory,
    *,
    suffix: int,
):
    actor, organization_id, _, workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, suffix
    )
    incidents, lifecycle, actions = _services(
        runtime_session_factory, organization_id, workspace.id
    )
    incident = incidents.create_incident(
        actor,
        organization_id,
        workspace.id,
        HostedIncidentInput(
            title="Approval persistence",
            description="Human decision required",
            service_name="api",
            environment="production",
            source_provider="manual",
            source_type="operator",
            observed_at=NOW,
        ),
    )
    requested = incidents.request_triage(
        actor,
        organization_id,
        workspace.id,
        incident.id,
        idempotency_key=f"approval-{suffix}",
    )
    claimed = lifecycle.claim(
        _worker(),
        requested.job,
        worker_id="worker-a",
        lease_duration=timedelta(minutes=5),
    )
    lifecycle.complete(
        _worker(),
        claimed,
        JobHandlerOutcome(
            JobResultReference("triage_run", str(requested.run.id)),
            TriageCompletion(
                TriageOutput(
                    incident_summary="API incident",
                    service_name="api",
                    severity="HIGH",
                    likely_root_cause="Unknown",
                    recommended_actions=["Acknowledge incident"],
                    escalate=True,
                    confidence=0.5,
                ),
                (),
                10,
            ),
        ),
    )
    proposal = actions.list_for_triage_run(
        actor, organization_id, workspace.id, requested.run.id
    )[0]
    return actor, organization_id, workspace, proposal


def test_approval_is_durable_bound_and_machine_decider_is_rejected(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    requester, organization_id, workspace, proposal = _completed_proposal(
        postgres_database, runtime_session_factory, suffix=200
    )
    approver = _seed_admin(postgres_database, organization_id, 1200)
    service = _approval_service(runtime_session_factory)
    requested = service.request_approval(
        requester, organization_id, workspace.id, proposal.id
    )
    approved = _approval_service(
        runtime_session_factory, clock=lambda: NOW + timedelta(minutes=1)
    ).approve(approver, organization_id, workspace.id, requested.id)

    assert approved.binds(proposal)
    assert approved.state.value == "approved"
    with tenant_transaction(
        runtime_session_factory, TenantContext(organization_id, workspace.id)
    ) as session:
        assert session.scalar(select(func.count()).select_from(ApprovalRecord)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEventRecord)
                .where(AuditEventRecord.event_type.like("approval.%"))
            )
            == 2
        )

    with pytest.raises(IntegrityError):
        with postgres_database.migration_engine.begin() as connection:
            connection.execute(
                update(ApprovalRecord)
                .where(ApprovalRecord.id == UUID(str(approved.id)))
                .values(
                    decided_by_kind="system",
                    decided_by_id=None,
                    decided_by_system_name="aira-worker",
                )
            )

    with pytest.raises(IntegrityError):
        with postgres_database.migration_engine.begin() as connection:
            connection.execute(
                update(ApprovalRecord)
                .where(ApprovalRecord.id == UUID(str(approved.id)))
                .values(decided_by_id=UUID(str(requester.actor.actor_id)))
            )


@pytest.mark.parametrize(
    ("suffix", "second_decision"),
    [(201, "approve"), (204, "reject")],
)
def test_active_request_and_decision_are_concurrently_serialized(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
    suffix: int,
    second_decision: str,
) -> None:
    requester, organization_id, workspace, proposal = _completed_proposal(
        postgres_database, runtime_session_factory, suffix=suffix
    )
    first_approver = _seed_admin(postgres_database, organization_id, suffix + 1000)
    second_approver = _seed_admin(postgres_database, organization_id, suffix + 2000)
    service = _approval_service(runtime_session_factory)

    def request_once():
        return service.request_approval(
            requester, organization_id, workspace.id, proposal.id
        ).id

    with ThreadPoolExecutor(max_workers=2) as executor:
        request_ids = tuple(executor.map(lambda _: request_once(), range(2)))
    assert request_ids[0] == request_ids[1]

    decision_service = _approval_service(
        runtime_session_factory, clock=lambda: NOW + timedelta(minutes=1)
    )

    def decide(item):
        actor, decision = item
        try:
            if decision == "reject":
                return decision_service.reject(
                    actor,
                    organization_id,
                    workspace.id,
                    request_ids[0],
                    reason="Target changed",
                ).state.value
            return decision_service.approve(
                actor, organization_id, workspace.id, request_ids[0]
            ).state.value
        except ApprovalConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(
            executor.map(
                decide,
                ((first_approver, "approve"), (second_approver, second_decision)),
            )
        )
    assert outcomes.count("conflict") == 1
    assert set(outcomes) <= {"approved", "rejected", "conflict"}

    with tenant_transaction(
        runtime_session_factory, TenantContext(organization_id, workspace.id)
    ) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEventRecord)
                .where(
                    AuditEventRecord.event_type.in_(
                        ("approval.approved", "approval.rejected")
                    )
                )
            )
            == 1
        )


def test_approval_and_expiry_race_cannot_approve_at_boundary(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    requester, organization_id, workspace, proposal = _completed_proposal(
        postgres_database, runtime_session_factory, suffix=205
    )
    approver = _seed_admin(postgres_database, organization_id, 1205)
    requested = _approval_service(runtime_session_factory).request_approval(
        requester, organization_id, workspace.id, proposal.id
    )
    service = _approval_service(
        runtime_session_factory, clock=lambda: requested.expires_at
    )

    def approve_at_boundary():
        with pytest.raises(ApprovalConflict):
            service.approve(approver, organization_id, workspace.id, requested.id)

    def expire_at_boundary():
        service.expire_due(requester, organization_id, workspace.id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        tuple(
            executor.map(lambda call: call(), (approve_at_boundary, expire_at_boundary))
        )

    persisted = service.get_approval(
        requester, organization_id, workspace.id, requested.id
    )
    assert persisted.state.value == "expired"
    with tenant_transaction(
        runtime_session_factory, TenantContext(organization_id, workspace.id)
    ) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEventRecord)
                .where(AuditEventRecord.event_type == "approval.expired")
            )
            == 1
        )


def test_stale_proposal_is_cancelled_and_rls_fails_closed(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    requester, organization_id, workspace, proposal = _completed_proposal(
        postgres_database, runtime_session_factory, suffix=202
    )
    approver = _seed_admin(postgres_database, organization_id, 1203)
    service = _approval_service(runtime_session_factory)
    requested = service.request_approval(
        requester, organization_id, workspace.id, proposal.id
    )
    with postgres_database.migration_engine.begin() as connection:
        connection.execute(
            update(ActionProposalRecord)
            .where(ActionProposalRecord.id == UUID(str(proposal.id)))
            .values(normalized_action_hash="c" * 64)
        )

    with pytest.raises(ApprovalConflict, match="stale"):
        _approval_service(
            runtime_session_factory, clock=lambda: NOW + timedelta(minutes=1)
        ).approve(approver, organization_id, workspace.id, requested.id)
    assert (
        service.get_approval(
            requester, organization_id, workspace.id, requested.id
        ).state.value
        == "cancelled"
    )

    with Session(postgres_database.runtime_engine) as session, session.begin():
        assert session.scalar(select(func.count()).select_from(ApprovalRecord)) == 0
    with tenant_transaction(
        runtime_session_factory,
        TenantContext(organization_id, _id(type(workspace.id), 9999)),
    ) as session:
        assert session.scalar(select(func.count()).select_from(ApprovalRecord)) == 0

    _, other_organization_id, other_workspace, other_proposal = _completed_proposal(
        postgres_database, runtime_session_factory, suffix=203
    )
    with tenant_transaction(
        runtime_session_factory,
        TenantContext(other_organization_id, other_workspace.id),
    ) as session:
        assert session.scalar(select(func.count()).select_from(ApprovalRecord)) == 0

    with pytest.raises(IntegrityError):
        with postgres_database.migration_engine.begin() as connection:
            connection.execute(
                update(ApprovalRecord)
                .where(ApprovalRecord.id == UUID(str(requested.id)))
                .values(action_id=UUID(str(other_proposal.id)))
            )
