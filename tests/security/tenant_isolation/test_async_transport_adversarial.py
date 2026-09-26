"""Forged queue identifiers cannot establish tenant or job authority."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.application.jobs import JobNotFound
from app.authorization.service import AuthorizationDenied
from app.domain.common import ActorKind, ActorReference, CorrelationContext
from app.domain.identifiers import CorrelationId, JobId
from app.domain.operations import Job, JobKind, JobResultReference, JobState
from app.jobs.contracts import QueueMessage
from app.jobs.envelope import JobDispatchEnvelope
from app.worker.orchestration import JobHandlerRegistry, MessageDisposition, WorkerMessageProcessor

from .fixtures import SCOPES, worker

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
JOB_ID = JobId("00000000-0000-4000-8000-000000000601")
FOREIGN_JOB_ID = JobId("00000000-0000-4000-8000-000000000602")
DISPATCH_ID = UUID("00000000-0000-4000-8000-000000000603")
FOREIGN_DISPATCH_ID = UUID("00000000-0000-4000-8000-000000000604")


def _job() -> Job:
    return Job(
        id=JOB_ID,
        scope=SCOPES["a1"],
        kind=JobKind.INDEX_BUILD,
        subject_type="knowledge_index_version",
        subject_id="00000000-0000-4000-8000-000000000605",
        state=JobState.PENDING,
        created_by=ActorReference(ActorKind.SYSTEM, system_name="scheduler"),
        created_at=NOW,
        updated_at=NOW,
        correlation=CorrelationContext(CorrelationId.new(), job_id=JOB_ID),
        idempotency_key="index:605",
        payload_version=1,
        payload=(("knowledge_index_version_id", "00000000-0000-4000-8000-000000000605"),),
        payload_hash="a" * 64,
        available_at=NOW,
    )


class Dispatch:
    def __init__(self, job: Job) -> None:
        self.id = DISPATCH_ID
        self.scope = job.scope
        self.job_id = job.id
        self.dispatch_generation = job.dispatch_generation


class AuthoritativeJobs:
    def __init__(self) -> None:
        self.job = _job()
        self.dispatch = Dispatch(self.job)
        self.loads = 0
        self.claims = 0
        self.completions = 0

    def get_execution_state(
        self, actor, organization_id, workspace_id, dispatch_id, job_id
    ):
        self.loads += 1
        if (organization_id, workspace_id) != (
            self.job.scope.organization_id,
            self.job.scope.workspace_id,
        ):
            raise AuthorizationDenied("Access denied")
        if dispatch_id != self.dispatch.id or job_id != self.job.id:
            raise JobNotFound("Job dispatch not found")
        return self.dispatch, self.job

    def claim_job(self, *args, worker_id, lease_duration, **kwargs):
        self.claims += 1
        self.job = self.job.claim(
            worker_id=worker_id,
            claim_token=uuid4(),
            lease_expires_at=NOW + lease_duration,
            at=NOW,
        )
        return self.job

    def renew_job_lease(self, *args, lease_duration, **kwargs):
        return self.job

    def complete_job(self, *args, **kwargs):
        self.completions += 1
        return self.job


class Queue:
    def change_visibility(self, message, timeout_seconds):
        return None


class Handler:
    def __init__(self) -> None:
        self.calls = 0

    def handle(self, actor, job, *, cancellation_requested):
        self.calls += 1
        return JobResultReference("knowledge_index_version", job.subject_id)


def _processor(jobs: AuthoritativeJobs):
    handler = Handler()
    processor = WorkerMessageProcessor(
        jobs,
        JobHandlerRegistry({JobKind.INDEX_BUILD: handler}),
        Queue(),
        worker(),
        worker_id="worker-a",
        heartbeat_interval_seconds=3600,
        clock=lambda: NOW,
    )
    return processor, handler


def _body(jobs: AuthoritativeJobs) -> dict:
    return json.loads(
        JobDispatchEnvelope(
            jobs.job.id,
            jobs.dispatch.id,
            jobs.job.dispatch_generation,
            jobs.job.scope.organization_id,
            jobs.job.scope.workspace_id,
            jobs.job.correlation.correlation_id,
        ).to_json()
    )


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    (
        ("job_id", str(FOREIGN_JOB_ID), MessageDisposition.DELETE),
        ("dispatch_id", str(FOREIGN_DISPATCH_ID), MessageDisposition.DELETE),
        ("routing_workspace_id", str(SCOPES["b1"].workspace_id), MessageDisposition.DELETE),
        ("routing_organization_id", str(SCOPES["b1"].organization_id), MessageDisposition.DELETE),
        ("correlation_id", str(CorrelationId.new()), MessageDisposition.RETAIN),
        ("dispatch_generation", 99, MessageDisposition.DELETE),
    ),
)
def test_forged_transport_fields_never_reach_handler_or_mutate_job(
    field,
    value,
    expected,
) -> None:
    jobs = AuthoritativeJobs()
    processor, handler = _processor(jobs)
    body = _body(jobs)
    body[field] = value

    assert processor.process(QueueMessage(json.dumps(body), "receipt")) is expected
    assert handler.calls == 0
    assert jobs.claims == 0
    assert jobs.completions == 0
    assert jobs.job.state is JobState.PENDING


def test_valid_envelope_uses_reloaded_job_scope_not_transport_payload_object() -> None:
    jobs = AuthoritativeJobs()
    processor, handler = _processor(jobs)
    body = _body(jobs)
    body["unused_tenant_hint"] = str(SCOPES["b1"].workspace_id)

    assert processor.process(QueueMessage(json.dumps(body), "receipt")) is MessageDisposition.RETAIN
    assert jobs.loads == 0
    assert handler.calls == 0
    assert jobs.claims == 0
