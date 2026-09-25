"""Real PostgreSQL evidence for hosted incident and triage lifecycle safety."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select, update

from app.application.incidents import HostedIncidentInput, HostedIncidentService
from app.application.triage_jobs import HostedTriageLifecycle, TriageCompletion
from app.auth.context import trusted_system_actor
from app.authorization.permissions import Permission
from app.authorization.service import (
    AuthorizationService,
    SystemAuthorizationGrant,
)
from app.domain.identifiers import EvidenceId
from app.domain.incidents import Evidence, TriageRunState
from app.domain.operations import JobResultReference, JobState
from app.models.triage import TriageOutput
from app.persistence.postgres.authorization import (
    PostgresAuthorizationFactsRepository,
    PostgresTenantResourceValidator,
)
from app.persistence.postgres.incident_unit_of_work import (
    PostgresHostedIncidentUnitOfWork,
)
from app.persistence.postgres.models import EvidenceRecord, JobRecord, TriageRunRecord
from app.persistence.postgres.tenant import TenantContext, tenant_transaction
from app.worker.orchestration import JobHandlerOutcome

from .conftest import PostgresTestDatabase
from .test_document_persistence import _setup
from .test_workspace_persistence import NOW


def _worker():
    return trusted_system_actor(
        system_name="aira-worker",
        workload_issuer="https://workload.example",
        workload_subject="worker-role",
    )


def _services(runtime_session_factory, organization_id, workspace_id):
    authorization = AuthorizationService(
        PostgresAuthorizationFactsRepository(runtime_session_factory),
        PostgresTenantResourceValidator(runtime_session_factory),
        system_grants=(
            SystemAuthorizationGrant(
                "aira-worker",
                "https://workload.example",
                "worker-role",
                organization_id,
                frozenset({Permission.JOB_EXECUTE}),
                frozenset({workspace_id}),
            ),
        ),
    )
    factory = lambda context: PostgresHostedIncidentUnitOfWork(  # noqa: E731
        runtime_session_factory, context
    )
    return (
        HostedIncidentService(authorization, factory, clock=lambda: NOW),
        HostedTriageLifecycle(authorization, factory, clock=lambda: NOW),
    )


def test_request_completion_evidence_and_stale_claim_are_atomic(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    actor, organization_id, _, workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 190
    )
    service, lifecycle = _services(
        runtime_session_factory, organization_id, workspace.id
    )
    incident = service.create_incident(
        actor,
        organization_id,
        workspace.id,
        HostedIncidentInput(
            title="Checkout latency",
            description="p99 exceeded objective",
            service_name="checkout-api",
            environment="production",
            source_provider="manual",
            source_type="operator",
            observed_at=NOW,
            external_event_id="event-190",
        ),
    )
    first = service.request_triage(
        actor,
        organization_id,
        workspace.id,
        incident.id,
        idempotency_key="triage-190",
    )
    duplicate = service.request_triage(
        actor,
        organization_id,
        workspace.id,
        incident.id,
        idempotency_key="triage-190",
    )
    assert duplicate.run.id == first.run.id
    assert duplicate.job.id == first.job.id

    claimed = lifecycle.claim(
        _worker(),
        first.job,
        worker_id="worker-a",
        lease_duration=timedelta(minutes=5),
    )
    result = TriageOutput(
        incident_summary="Checkout is slow",
        service_name="checkout-api",
        severity="HIGH",
        likely_root_cause="Dependency timeout",
        recommended_actions=["Inspect dependencies"],
        escalate=True,
        confidence=0.8,
        evidence=[],
    )
    evidence = Evidence(
        id=EvidenceId.new(),
        scope=first.run.scope,
        triage_run=first.run.reference,
        type="runbook",
        source="checkout.md",
        reason="Documents timeout recovery",
        created_at=NOW,
        sequence=0,
        origin="tenant",
        document_id="doc-190",
        document_version_id="version-190",
        knowledge_index_version_id="index-190",
        chunk_index=3,
        score=0.9,
    )
    outcome = JobHandlerOutcome(
        JobResultReference("triage_run", str(first.run.id)),
        TriageCompletion(result, (evidence,), 25),
    )
    completed = lifecycle.complete(_worker(), claimed, outcome)
    assert completed.state is JobState.SUCCEEDED
    view = service.get_triage(
        actor, organization_id, workspace.id, first.run.id
    )
    assert view.run.state is TriageRunState.SUCCEEDED
    assert view.run.legacy_triage_id == str(first.run.id)
    assert view.evidence[0].document_version_id == "version-190"

    with pytest.raises(Exception, match="stale"):
        lifecycle.complete(_worker(), claimed, outcome)


def test_triage_and_evidence_rls_fail_closed_across_tenants(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    first_actor, first_org, _, first_workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 191
    )
    _, second_org, _, second_workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 192
    )
    service, lifecycle = _services(
        runtime_session_factory, first_org, first_workspace.id
    )
    incident = service.create_incident(
        first_actor,
        first_org,
        first_workspace.id,
        HostedIncidentInput(
            title="API errors",
            description="Elevated error rate",
            service_name="api",
            environment="production",
            source_provider="manual",
            source_type="operator",
            observed_at=NOW,
        ),
    )
    requested = service.request_triage(
        first_actor,
        first_org,
        first_workspace.id,
        incident.id,
        idempotency_key="triage-191",
    )
    claimed = lifecycle.claim(
        _worker(),
        requested.job,
        worker_id="worker-a",
        lease_duration=timedelta(minutes=5),
    )
    result = TriageOutput(
        incident_summary="API errors",
        service_name="api",
        severity="HIGH",
        likely_root_cause="Unknown",
        recommended_actions=["Inspect logs"],
        escalate=True,
        confidence=0.5,
    )
    lifecycle.complete(
        _worker(),
        claimed,
        JobHandlerOutcome(
            JobResultReference("triage_run", str(requested.run.id)),
            TriageCompletion(
                result,
                (
                    Evidence(
                        id=EvidenceId.new(),
                        scope=requested.run.scope,
                        triage_run=requested.run.reference,
                        type="incident",
                        source="incident payload",
                        reason="Carries the original alert",
                        created_at=NOW,
                        sequence=0,
                        origin="tenant",
                    ),
                ),
                10,
            ),
        ),
    )

    with runtime_session_factory.begin() as session:
        assert session.scalar(select(func.count()).select_from(TriageRunRecord)) == 0
        assert session.scalar(select(func.count()).select_from(EvidenceRecord)) == 0
    with tenant_transaction(
        runtime_session_factory, TenantContext(second_org, second_workspace.id)
    ) as session:
        assert session.scalar(select(func.count()).select_from(TriageRunRecord)) == 0
        assert session.scalar(select(func.count()).select_from(EvidenceRecord)) == 0


def test_lease_recovery_drift_is_reconciled_before_redispatch(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    actor, organization_id, _, workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 193
    )
    service, lifecycle = _services(
        runtime_session_factory, organization_id, workspace.id
    )
    incident = service.create_incident(
        actor,
        organization_id,
        workspace.id,
        HostedIncidentInput(
            title="Worker crash",
            description="Lease expired",
            service_name="worker",
            environment="production",
            source_provider="manual",
            source_type="operator",
            observed_at=NOW,
        ),
    )
    requested = service.request_triage(
        actor,
        organization_id,
        workspace.id,
        incident.id,
        idempotency_key="triage-193",
    )
    lifecycle.claim(
        _worker(),
        requested.job,
        worker_id="worker-a",
        lease_duration=timedelta(minutes=5),
    )

    with postgres_database.migration_engine.begin() as connection:
        connection.execute(
            update(JobRecord)
            .where(JobRecord.id == UUID(str(requested.job.id)))
            .values(
                state="pending",
                claimed_by=None,
                claim_token=None,
                lease_expires_at=None,
                state_version=JobRecord.state_version + 1,
                dispatch_generation=JobRecord.dispatch_generation + 1,
            )
        )

    assert lifecycle.reconcile_scope(
        _worker(), organization_id, workspace.id
    ) == 1
    view = service.get_triage(actor, organization_id, workspace.id, requested.run.id)
    assert view.run.state is TriageRunState.QUEUED
    assert view.job.state is JobState.PENDING


def test_completion_loses_to_requested_cancellation_without_partial_result(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    actor, organization_id, _, workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 194
    )
    service, lifecycle = _services(
        runtime_session_factory, organization_id, workspace.id
    )
    incident = service.create_incident(
        actor,
        organization_id,
        workspace.id,
        HostedIncidentInput(
            title="Cancellation race",
            description="Operator cancelled during execution",
            service_name="api",
            environment="production",
            source_provider="manual",
            source_type="operator",
            observed_at=NOW,
        ),
    )
    requested = service.request_triage(
        actor,
        organization_id,
        workspace.id,
        incident.id,
        idempotency_key="triage-194",
    )
    claimed = lifecycle.claim(
        _worker(),
        requested.job,
        worker_id="worker-a",
        lease_duration=timedelta(minutes=5),
    )
    service.cancel_triage(actor, organization_id, workspace.id, requested.run.id)
    result = TriageOutput(
        incident_summary="Should not persist",
        service_name="api",
        severity="LOW",
        likely_root_cause="Cancelled",
        recommended_actions=["None"],
        escalate=False,
        confidence=0.1,
    )
    outcome = JobHandlerOutcome(
        JobResultReference("triage_run", str(requested.run.id)),
        TriageCompletion(result, (), 10),
    )

    with pytest.raises(Exception, match="stale"):
        lifecycle.complete(_worker(), claimed, outcome)
    lifecycle.acknowledge_cancellation(_worker(), claimed)
    view = service.get_triage(
        actor, organization_id, workspace.id, requested.run.id
    )
    assert view.run.state is TriageRunState.CANCELLED
    assert view.run.result is None
    assert view.job.state is JobState.CANCELLED
