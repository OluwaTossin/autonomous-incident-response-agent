"""Transport-neutral durable job service and handler tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import pytest

from app.application.jobs import (
    HostedJobService,
    JobConflict,
    JobIdempotencyConflict,
    JobListCursor,
    JobNotClaimable,
    KnowledgeIndexBuildJobHandler,
    KnowledgeIndexBuildJobPayload,
    TransientJobExecutionError,
)
from app.auth.context import ActorContext, AuthenticationMethod, trusted_system_actor
from app.authorization.permissions import Permission
from app.authorization.service import (
    AuthorizationDenied,
    AuthorizationService,
    HumanAuthorizationFacts,
    SystemAuthorizationGrant,
)
from app.domain.common import ActorKind, ActorReference
from app.domain.identifiers import (
    KnowledgeIndexVersionId,
    MembershipId,
    OrganizationId,
    UserId,
    WorkspaceId,
)
from app.domain.operations import JobErrorCategory, JobFailure, JobState
from app.domain.tenancy import MembershipRole, WorkspaceAccessMode
from app.knowledge.contracts import (
    HostedKnowledgeIndexReference,
    KnowledgeBundlePublication,
    PublishedKnowledgeIndexReference,
)

NOW = datetime(2026, 9, 24, 20, 0, tzinfo=UTC)


def _id(identifier_type, suffix: int):
    return identifier_type(f"00000000-0000-4000-8000-{suffix:012d}")


ORG = _id(OrganizationId, 1)
WORKSPACE = _id(WorkspaceId, 2)
INDEX = _id(KnowledgeIndexVersionId, 3)


def _human() -> ActorContext:
    return ActorContext(
        ActorReference(ActorKind.HUMAN, actor_id=_id(UserId, 4)),
        AuthenticationMethod.OIDC,
        issuer="https://issuer.example",
        external_subject="operator",
    )


def _worker() -> ActorContext:
    return trusted_system_actor(
        system_name="aira-worker",
        workload_issuer="https://workload.example",
        workload_subject="worker-role",
    )


class Facts:
    def human_facts(self, actor, organization_id, workspace_id):
        if organization_id != ORG or workspace_id != WORKSPACE:
            return None
        return HumanAuthorizationFacts(
            _id(MembershipId, 5),
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


class Store:
    def __init__(self):
        self.jobs = {}
        self.dispatches = []
        self.audits = []


class Jobs:
    def __init__(self, store):
        self.store = store

    def create_or_get(self, job):
        for existing in self.store.jobs.values():
            if (
                existing.scope == job.scope
                and existing.kind == job.kind
                and existing.idempotency_key == job.idempotency_key
            ):
                return existing, False
        self.store.jobs[job.id] = job
        return job, True

    def get(self, job_id, *, for_update=False):
        return self.store.jobs.get(job_id)

    def list(self, *, limit, before: JobListCursor | None):
        values = sorted(
            self.store.jobs.values(),
            key=lambda job: (job.created_at, str(job.id)),
            reverse=True,
        )
        if before is not None:
            values = [
                job
                for job in values
                if (job.created_at, str(job.id))
                < (before.created_at, str(before.job_id))
            ]
        return values[:limit]

    def list_expired(self, *, at, limit):
        return [
            job
            for job in self.store.jobs.values()
            if job.state is JobState.RUNNING and job.lease_expires_at <= at
        ][:limit]

    def save(self, job, *, expected_version):
        current = self.store.jobs[job.id]
        if current.state_version != expected_version:
            raise JobConflict("stale")
        self.store.jobs[job.id] = job


class Dispatches:
    def __init__(self, store):
        self.store = store

    def add(self, job, *, at):
        self.store.dispatches.append((job.id, job.dispatch_generation, job.available_at))


class Audits:
    def __init__(self, store):
        self.store = store

    def add(self, event):
        self.store.audits.append(event)


class Uow:
    def __init__(self, store):
        self.jobs = Jobs(store)
        self.dispatches = Dispatches(store)
        self.audit_events = Audits(store)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


def _service(store=None, clock=None):
    store = store or Store()
    clock = clock or Clock()
    authorization = AuthorizationService(
        Facts(),
        Resources(),
        system_grants=(
            SystemAuthorizationGrant(
                "aira-worker",
                "https://workload.example",
                "worker-role",
                ORG,
                frozenset({Permission.JOB_EXECUTE, Permission.KNOWLEDGE_MANAGE}),
                frozenset({WORKSPACE}),
            ),
        ),
    )
    return HostedJobService(
        authorization,
        lambda context: Uow(store),
        clock=clock,
        monotonic=lambda: 1.0,
    ), store, clock


def _create(service, *, key="index:3", index=INDEX, max_attempts=3):
    return service.create_index_build_job(
        _human(),
        ORG,
        WORKSPACE,
        KnowledgeIndexBuildJobPayload(index),
        idempotency_key=key,
        max_attempts=max_attempts,
    )


def test_create_is_idempotent_and_conflicting_payload_fails() -> None:
    service, store, _ = _service()
    created = _create(service)
    reused = _create(service)

    assert reused.id == created.id
    assert store.dispatches == [(created.id, 1, NOW)]
    assert [event.event_type for event in store.audits] == ["job.created"]
    assert "knowledge_index_version_id" not in str(store.audits[0].details)

    with pytest.raises(JobIdempotencyConflict):
        _create(service, index=_id(KnowledgeIndexVersionId, 99))


def test_invalid_payload_and_inactive_workspace_are_rejected() -> None:
    service, _, _ = _service()
    with pytest.raises(ValueError, match="Unsupported"):
        service.create_index_build_job(
            _human(),
            ORG,
            WORKSPACE,
            KnowledgeIndexBuildJobPayload(INDEX, schema_version=2),
            idempotency_key="invalid",
        )

    class InactiveResources:
        def is_active(self, organization_id, workspace_id):
            return False

    store = Store()
    inactive = HostedJobService(
        AuthorizationService(Facts(), InactiveResources()),
        lambda context: Uow(store),
        clock=lambda: NOW,
    )
    with pytest.raises(AuthorizationDenied):
        inactive.create_index_build_job(
            _human(),
            ORG,
            WORKSPACE,
            KnowledgeIndexBuildJobPayload(INDEX),
            idempotency_key="inactive",
        )


def test_claim_retry_backoff_stale_completion_and_success() -> None:
    service, store, clock = _service()
    pending = _create(service)
    first = service.claim_job(
        _worker(),
        ORG,
        WORKSPACE,
        pending.id,
        worker_id="worker-a",
        lease_duration=timedelta(minutes=1),
    )
    retry = service.fail_job(
        _worker(),
        ORG,
        WORKSPACE,
        pending.id,
        first.claim_token,
        JobFailure(
            "dependency_timeout",
            JobErrorCategory.TRANSIENT,
            True,
            "Dependency timed out",
        ),
    )

    assert retry.state is JobState.PENDING
    assert retry.available_at == NOW + timedelta(seconds=30)
    assert retry.dispatch_generation == 2
    with pytest.raises(JobNotClaimable):
        service.claim_job(
            _worker(),
            ORG,
            WORKSPACE,
            pending.id,
            worker_id="worker-b",
            lease_duration=timedelta(minutes=1),
        )

    clock.now += timedelta(seconds=31)
    second = service.claim_job(
        _worker(),
        ORG,
        WORKSPACE,
        pending.id,
        worker_id="worker-b",
        lease_duration=timedelta(minutes=1),
    )
    with pytest.raises(JobNotClaimable):
        service.complete_job(
            _worker(),
            ORG,
            WORKSPACE,
            pending.id,
            first.claim_token,
            _result(),
        )
    completed = service.complete_job(
        _worker(),
        ORG,
        WORKSPACE,
        pending.id,
        second.claim_token,
        _result(),
    )

    assert completed.state is JobState.SUCCEEDED
    assert completed.attempt_count == 2
    assert len(store.dispatches) == 2


def test_pending_cancel_and_running_cancellation_request() -> None:
    service, _, _ = _service()
    pending = _create(service)
    assert service.cancel_job(_human(), ORG, WORKSPACE, pending.id).state is JobState.CANCELLED

    running_job = _create(service, key="index:running")
    running = service.claim_job(
        _worker(),
        ORG,
        WORKSPACE,
        running_job.id,
        worker_id="worker-a",
        lease_duration=timedelta(minutes=1),
    )
    requested = service.cancel_job(_human(), ORG, WORKSPACE, running.id)
    assert requested.state is JobState.RUNNING
    assert requested.cancellation_requested_at == NOW
    cancelled = service.acknowledge_cancellation(
        _worker(), ORG, WORKSPACE, running.id, running.claim_token
    )
    assert cancelled.state is JobState.CANCELLED


def test_expired_lease_recovery_retries_then_exhausts() -> None:
    service, _, clock = _service()
    pending = _create(service, max_attempts=1)
    service.claim_job(
        _worker(),
        ORG,
        WORKSPACE,
        pending.id,
        worker_id="worker-a",
        lease_duration=timedelta(seconds=10),
    )
    assert service.recover_expired_jobs(_worker(), ORG, WORKSPACE) == ()
    clock.now += timedelta(seconds=11)

    recovered = service.recover_expired_jobs(_worker(), ORG, WORKSPACE)

    assert len(recovered) == 1
    assert recovered[0].state is JobState.FAILED
    assert recovered[0].last_error.code == "lease_expired"


class Operation:
    def __init__(self, outcome="success"):
        self.outcome = outcome
        self.calls = 0

    def build_publish_activate(
        self, actor, organization_id, workspace_id, *, index_version_id=None
    ):
        self.calls += 1
        if self.outcome == "transient":
            raise TransientJobExecutionError("temporary")
        if self.outcome == "permanent":
            raise RuntimeError("unsafe detail")
        return PublishedKnowledgeIndexReference(
            HostedKnowledgeIndexReference(
                scope=store_scope(),
                index_version_id=index_version_id,
                source_document_versions=(),
            ),
            KnowledgeBundlePublication("knowledge-indexes/safe/", 1, "a" * 64),
        )


def store_scope():
    from app.domain.common import WorkspaceScope

    return WorkspaceScope(ORG, WORKSPACE)


def _result():
    from app.domain.operations import JobResultReference

    return JobResultReference("knowledge_index_version", str(INDEX))


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [("success", JobState.SUCCEEDED), ("transient", JobState.PENDING), ("permanent", JobState.FAILED)],
)
def test_index_build_handler_delegates_and_classifies_failures(outcome, expected) -> None:
    service, _, _ = _service()
    job = _create(service)
    operation = Operation(outcome)
    handler = KnowledgeIndexBuildJobHandler(service, operation)

    result = handler.execute(
        _worker(), ORG, WORKSPACE, job.id, worker_id="worker-a"
    )

    assert result.state is expected
    assert operation.calls == 1
    if expected is JobState.SUCCEEDED:
        with pytest.raises(JobNotClaimable):
            handler.execute(_worker(), ORG, WORKSPACE, job.id, worker_id="worker-b")
        assert operation.calls == 1
