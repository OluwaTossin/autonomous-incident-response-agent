"""Real PostgreSQL concurrency, RLS, and audit tests for durable jobs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.application.jobs import (
    HostedJobService,
    JobConflict,
    JobIdempotencyConflict,
    JobNotClaimable,
    KnowledgeIndexBuildJobPayload,
)
from app.auth.context import (
    ActorContext,
    AuthenticationMethod,
    trusted_system_actor,
)
from app.authorization.permissions import Permission
from app.authorization.service import (
    AuthorizationDenied,
    AuthorizationService,
    SystemAuthorizationGrant,
)
from app.domain.common import ActorKind, ActorReference
from app.domain.identifiers import (
    KnowledgeIndexVersionId,
    ServiceAccountId,
)
from app.domain.operations import (
    JobErrorCategory,
    JobFailure,
    JobResultReference,
    JobState,
)
from app.persistence.postgres.authorization import (
    PostgresAuthorizationFactsRepository,
    PostgresTenantResourceValidator,
)
from app.persistence.postgres.job_unit_of_work import PostgresJobUnitOfWork
from app.persistence.postgres.models import (
    AuditEventRecord,
    JobDispatchRecord,
    JobRecord,
)

from .conftest import PostgresTestDatabase
from .test_document_persistence import _setup
from .test_workspace_persistence import NOW


def _index(suffix: int) -> KnowledgeIndexVersionId:
    return KnowledgeIndexVersionId(f"00000000-0000-4000-8000-{suffix:012d}")


def _worker():
    return trusted_system_actor(
        system_name="aira-worker",
        workload_issuer="https://workload.example",
        workload_subject="worker-role",
    )


def _service(runtime_session_factory, organization_id, workspace_id, *, clock=lambda: NOW):
    authorization = AuthorizationService(
        PostgresAuthorizationFactsRepository(runtime_session_factory),
        PostgresTenantResourceValidator(runtime_session_factory),
        system_grants=(
            SystemAuthorizationGrant(
                "aira-worker",
                "https://workload.example",
                "worker-role",
                organization_id,
                frozenset({Permission.JOB_EXECUTE, Permission.KNOWLEDGE_MANAGE}),
                frozenset({workspace_id}),
            ),
        ),
    )
    return HostedJobService(
        authorization,
        lambda context: PostgresJobUnitOfWork(runtime_session_factory, context),
        clock=clock,
        monotonic=lambda: 1.0,
    )


def _create(service, actor, organization_id, workspace_id, *, suffix=1, key="index:1"):
    return service.create_index_build_job(
        actor,
        organization_id,
        workspace_id,
        KnowledgeIndexBuildJobPayload(_index(suffix)),
        idempotency_key=key,
    )


def test_concurrent_idempotent_creation_has_one_job_dispatch_and_audit(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    actor, organization_id, _, workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 140
    )
    service = _service(runtime_session_factory, organization_id, workspace.id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        jobs = list(
            executor.map(
                lambda _: _create(service, actor, organization_id, workspace.id),
                range(2),
            )
        )

    assert jobs[0].id == jobs[1].id
    pending_dispatches = service.list_unpublished_dispatches(
        _worker(), organization_id, workspace.id
    )
    assert len(pending_dispatches) == 1
    assert service.mark_dispatch_published(
        _worker(), organization_id, workspace.id, pending_dispatches[0].id
    )
    assert service.list_unpublished_dispatches(
        _worker(), organization_id, workspace.id
    ) == ()
    with Session(postgres_database.migration_engine) as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        assert session.scalar(select(func.count()).select_from(JobDispatchRecord)) == 1
        events = session.scalars(
            select(AuditEventRecord).where(
                AuditEventRecord.target_id == str(jobs[0].id)
            )
        ).all()
        assert [event.event_type for event in events] == ["job.created"]
        assert "knowledge_index_version_id" not in str(events[0].details)

    with pytest.raises(JobIdempotencyConflict):
        _create(
            service,
            actor,
            organization_id,
            workspace.id,
            suffix=2,
            key="index:1",
        )


def test_concurrent_claim_retry_and_stale_worker_are_database_serialized(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    actor, organization_id, _, workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 150
    )
    service = _service(runtime_session_factory, organization_id, workspace.id)
    job = _create(service, actor, organization_id, workspace.id)

    def claim():
        return service.claim_job(
            _worker(),
            organization_id,
            workspace.id,
            job.id,
            worker_id="worker-a",
            lease_duration=timedelta(minutes=1),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(claim) for _ in range(2)]
        outcomes = []
        for future in futures:
            try:
                outcomes.append(future.result())
            except JobNotClaimable:
                pass
    assert len(outcomes) == 1
    claimed = outcomes[0]
    retry = service.fail_job(
        _worker(),
        organization_id,
        workspace.id,
        job.id,
        claimed.claim_token,
        JobFailure(
            "dependency_timeout",
            JobErrorCategory.TRANSIENT,
            True,
            "Dependency timed out",
        ),
    )
    assert retry.state is JobState.PENDING
    assert retry.attempt_count == 1
    with pytest.raises(JobNotClaimable):
        service.complete_job(
            _worker(),
            organization_id,
            workspace.id,
            job.id,
            claimed.claim_token,
            JobResultReference("knowledge_index_version", str(_index(1))),
        )


def test_lease_recovery_and_job_rls_fail_closed(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    actor, organization_id, _, workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 160
    )
    now = [NOW]
    service = _service(
        runtime_session_factory,
        organization_id,
        workspace.id,
        clock=lambda: now[0],
    )
    job = _create(service, actor, organization_id, workspace.id)
    service.claim_job(
        _worker(),
        organization_id,
        workspace.id,
        job.id,
        worker_id="worker-a",
        lease_duration=timedelta(seconds=10),
    )
    assert service.recover_expired_jobs(
        _worker(), organization_id, workspace.id
    ) == ()
    now[0] += timedelta(seconds=11)

    recovered = service.recover_expired_jobs(
        _worker(), organization_id, workspace.id
    )

    assert len(recovered) == 1
    assert recovered[0].state is JobState.PENDING
    assert recovered[0].dispatch_generation == 2
    with runtime_session_factory.begin() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 0
        assert session.scalar(select(func.count()).select_from(JobDispatchRecord)) == 0

    unauthorized_worker = trusted_system_actor(
        system_name="unknown-worker",
        workload_issuer="https://workload.example",
        workload_subject="unknown-role",
    )
    with pytest.raises(AuthorizationDenied):
        service.recover_expired_jobs(
            unauthorized_worker, organization_id, workspace.id
        )

    with Session(postgres_database.migration_engine) as session:
        record = session.get(JobRecord, UUID(str(job.id)))
        assert record.state == "pending"
        assert record.claim_token is None
        assert session.scalar(select(func.count()).select_from(JobDispatchRecord)) == 2


def test_completion_cancellation_and_retry_races_have_one_durable_outcome(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    actor, organization_id, _, workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 170
    )
    service = _service(runtime_session_factory, organization_id, workspace.id)
    completion_job = _create(service, actor, organization_id, workspace.id)
    claimed = service.claim_job(
        _worker(),
        organization_id,
        workspace.id,
        completion_job.id,
        worker_id="worker-a",
        lease_duration=timedelta(minutes=1),
    )

    def complete():
        return service.complete_job(
            _worker(),
            organization_id,
            workspace.id,
            completion_job.id,
            claimed.claim_token,
            JobResultReference("knowledge_index_version", str(_index(1))),
        )

    def cancel():
        return service.cancel_job(
            actor, organization_id, workspace.id, completion_job.id
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(complete), executor.submit(cancel)]
        for future in futures:
            try:
                future.result()
            except JobConflict:
                pass

    assert service.get_job(
        actor, organization_id, workspace.id, completion_job.id
    ).state is JobState.SUCCEEDED

    retry_job = _create(
        service,
        actor,
        organization_id,
        workspace.id,
        suffix=2,
        key="index:retry-race",
    )
    retry_claim = service.claim_job(
        _worker(),
        organization_id,
        workspace.id,
        retry_job.id,
        worker_id="worker-a",
        lease_duration=timedelta(minutes=1),
    )
    failure = JobFailure(
        "dependency_timeout",
        JobErrorCategory.TRANSIENT,
        True,
        "Dependency timed out",
    )

    def fail():
        return service.fail_job(
            _worker(),
            organization_id,
            workspace.id,
            retry_job.id,
            retry_claim.claim_token,
            failure,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(fail) for _ in range(2)]
        successes = 0
        for future in futures:
            try:
                future.result()
                successes += 1
            except JobNotClaimable:
                pass
    assert successes == 1
    with Session(postgres_database.migration_engine) as session:
        record = session.get(JobRecord, UUID(str(retry_job.id)))
        assert record.state == "pending"
        assert record.dispatch_generation == 2


def test_unauthorized_service_account_cannot_read_or_execute_jobs(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    actor, organization_id, _, workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 180
    )
    service = _service(runtime_session_factory, organization_id, workspace.id)
    job = _create(service, actor, organization_id, workspace.id)
    service_account = ActorContext(
        ActorReference(
            ActorKind.SERVICE_ACCOUNT,
            actor_id=ServiceAccountId(
                "00000000-0000-4000-8000-000000000180"
            ),
        ),
        AuthenticationMethod.SERVICE_ACCOUNT,
        credential_id="credential-180",
    )

    with pytest.raises(AuthorizationDenied):
        service.get_job(
            service_account, organization_id, workspace.id, job.id
        )
    with pytest.raises(AuthorizationDenied):
        service.claim_job(
            service_account,
            organization_id,
            workspace.id,
            job.id,
            worker_id="untrusted",
            lease_duration=timedelta(minutes=1),
        )
