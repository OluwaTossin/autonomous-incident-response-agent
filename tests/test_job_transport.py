"""Queue envelope, outbox publisher, SQS adapter, and worker orchestration tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.application.job_dispatch import OutboxDispatcher
from app.application.jobs import JobDispatch, JobNotClaimable, TransientJobExecutionError
from app.auth.context import trusted_system_actor
from app.authorization.service import AuthorizationDenied
from app.domain.common import ActorKind, ActorReference, CorrelationContext, WorkspaceScope
from app.domain.identifiers import (
    CorrelationId,
    JobId,
    OrganizationId,
    WorkspaceId,
)
from app.domain.operations import Job, JobKind, JobResultReference, JobState
from app.jobs.contracts import QueueMessage
from app.jobs.envelope import JobDispatchEnvelope, MessageEnvelopeError
from app.jobs.sqs import Boto3SqsQueue, create_sqs_client
from app.worker.orchestration import (
    JobHandlerRegistry,
    MessageDisposition,
    WorkerHeartbeat,
    WorkerMessageProcessor,
)
from app.worker.runtime import PollingWorker, WorkerRuntimeConfig

NOW = datetime(2026, 9, 24, 21, 0, tzinfo=UTC)
ORG = OrganizationId("00000000-0000-4000-8000-000000000001")
WORKSPACE = WorkspaceId("00000000-0000-4000-8000-000000000002")
OTHER_WORKSPACE = WorkspaceId("00000000-0000-4000-8000-000000000003")
DISPATCH_ID = UUID("00000000-0000-4000-8000-000000000004")
JOB_ID = JobId("00000000-0000-4000-8000-000000000005")


def _actor():
    return trusted_system_actor(
        system_name="aira-worker",
        workload_issuer="https://workload.example",
        workload_subject="worker-role",
    )


def _job(*, state=JobState.PENDING, generation=1, available_at=NOW) -> Job:
    base = Job(
        id=JOB_ID,
        scope=WorkspaceScope(ORG, WORKSPACE),
        kind=JobKind.INDEX_BUILD,
        subject_type="knowledge_index_version",
        subject_id="00000000-0000-4000-8000-000000000006",
        state=JobState.PENDING,
        created_by=ActorReference(ActorKind.SYSTEM, system_name="scheduler"),
        created_at=NOW,
        updated_at=NOW,
        correlation=CorrelationContext(CorrelationId.new(), job_id=JOB_ID),
        idempotency_key="index:6",
        payload_version=1,
        payload=(("knowledge_index_version_id", "00000000-0000-4000-8000-000000000006"),),
        payload_hash="a" * 64,
        available_at=available_at,
        dispatch_generation=generation,
    )
    if state is JobState.RUNNING:
        return base.claim(
            worker_id="other-worker",
            claim_token=uuid4(),
            lease_expires_at=NOW + timedelta(minutes=5),
            at=NOW,
        )
    if state is JobState.CANCELLED:
        return base.request_cancel(at=NOW)
    return base


def _dispatch(job: Job, *, claimed=False) -> JobDispatch:
    return JobDispatch(
        id=DISPATCH_ID,
        scope=job.scope,
        job_id=job.id,
        dispatch_generation=job.dispatch_generation,
        available_at=job.available_at,
        created_at=NOW,
        claimed_by="publisher" if claimed else None,
        claim_token=uuid4() if claimed else None,
        claim_expires_at=NOW + timedelta(seconds=30) if claimed else None,
        publish_attempt_count=1 if claimed else 0,
    )


def _envelope(job: Job, dispatch: JobDispatch, *, workspace=WORKSPACE) -> str:
    return JobDispatchEnvelope(
        job.id,
        dispatch.id,
        dispatch.dispatch_generation,
        ORG,
        workspace,
    ).to_json()


class Queue:
    def __init__(self):
        self.sent = []
        self.deleted = []
        self.visibility = []
        self.received = []

    def send(self, message):
        self.sent.append(message)
        return "message-1"

    def send_batch(self, messages):
        self.sent.extend(messages)
        return tuple(f"message-{index}" for index, _ in enumerate(messages))

    def receive(self, **kwargs):
        self.receive_kwargs = kwargs
        values, self.received = tuple(self.received), []
        return values

    def delete(self, message):
        self.deleted.append(message)

    def change_visibility(self, message, timeout_seconds):
        self.visibility.append((message, timeout_seconds))


class DispatchService:
    def __init__(self, dispatch, queue, *, fail_ack=False):
        self.dispatch = dispatch
        self.queue = queue
        self.fail_ack = fail_ack
        self.events = []

    def claim_dispatches(self, *args, **kwargs):
        self.events.append("claim")
        return (self.dispatch,)

    def mark_dispatch_published(self, *args, **kwargs):
        assert self.queue.sent
        self.events.append("ack")
        return not self.fail_ack

    def release_dispatch_claim(self, *args, **kwargs):
        self.events.append("release")
        return True


class JobService:
    def __init__(self, job, dispatch):
        self.job = job
        self.dispatch = dispatch
        self.calls = []
        self.now = NOW

    def get_execution_state(self, actor, organization_id, workspace_id, dispatch_id, job_id):
        self.calls.append("load")
        if organization_id != ORG or workspace_id != WORKSPACE:
            raise AuthorizationDenied("denied")
        if dispatch_id != self.dispatch.id or job_id != self.job.id:
            raise LookupError("missing")
        return self.dispatch, self.job

    def claim_job(self, actor, organization_id, workspace_id, job_id, *, worker_id, lease_duration):
        self.calls.append("claim")
        try:
            self.job = self.job.claim(
                worker_id=worker_id,
                claim_token=uuid4(),
                lease_expires_at=self.now + lease_duration,
                at=self.now,
            )
        except Exception as exc:
            raise JobNotClaimable("not claimable") from exc
        return self.job

    def renew_job_lease(self, actor, organization_id, workspace_id, job_id, claim_token, *, lease_duration):
        self.calls.append("renew")
        self.job = self.job.renew_lease(
            claim_token,
            lease_expires_at=self.now + lease_duration,
            at=self.now,
        )
        return self.job

    def complete_job(self, actor, organization_id, workspace_id, job_id, claim_token, result):
        self.calls.append("complete")
        self.job = self.job.succeed(claim_token, result, at=self.now)
        return self.job

    def fail_job(self, actor, organization_id, workspace_id, job_id, claim_token, failure):
        self.calls.append("fail")
        self.job = self.job.fail_attempt(
            claim_token,
            failure,
            next_available_at=self.now + timedelta(seconds=30),
            at=self.now,
        )
        if self.job.state is JobState.PENDING:
            self.dispatch = replace(
                self.dispatch,
                dispatch_generation=self.job.dispatch_generation,
                available_at=self.job.available_at,
            )
        return self.job

    def acknowledge_cancellation(self, actor, organization_id, workspace_id, job_id, claim_token):
        self.calls.append("cancel")
        self.job = self.job.acknowledge_cancellation(claim_token, at=self.now)
        return self.job


class Handler:
    def __init__(self, service=None, outcome="success"):
        self.service = service
        self.outcome = outcome
        self.calls = []

    def handle(self, actor, job, *, cancellation_requested):
        self.calls.append(job.kind)
        assert self.service is None or "claim" in self.service.calls
        if self.outcome == "transient":
            raise TransientJobExecutionError("temporary")
        if self.outcome == "cancel":
            self.service.job = self.service.job.request_cancel(at=NOW)
            assert cancellation_requested()
            from app.application.jobs import JobCancellationRequested

            raise JobCancellationRequested("cancel")
        return JobResultReference("knowledge_index_version", job.subject_id)


def _processor(service, queue, handler=None, handlers=None):
    handler = handler or Handler(service)
    registry = JobHandlerRegistry(
        handlers if handlers is not None else {JobKind.INDEX_BUILD: handler}
    )
    return WorkerMessageProcessor(
        service,
        registry,
        queue,
        _actor(),
        worker_id="worker-a",
        heartbeat_interval_seconds=3600,
        clock=lambda: service.now,
    ), handler


def test_message_envelope_is_strict_versioned_and_identifier_only() -> None:
    job = _job()
    dispatch = _dispatch(job)
    raw = _envelope(job, dispatch)
    decoded = JobDispatchEnvelope.from_json(raw)

    assert decoded.job_id == job.id
    assert decoded.dispatch_generation == 1
    assert "attempt" not in raw
    assert "claim_token" not in raw
    assert "payload" not in raw
    with pytest.raises(MessageEnvelopeError):
        JobDispatchEnvelope.from_json(raw[:-1] + ',"secret":"x"}')
    with pytest.raises(MessageEnvelopeError):
        JobDispatchEnvelope.from_json("not-json")


def test_outbox_dispatcher_acknowledges_only_after_send_and_recovers_failures() -> None:
    job = _job()
    queue = Queue()
    dispatch = _dispatch(job, claimed=True)
    service = DispatchService(dispatch, queue)

    result = OutboxDispatcher(service, queue, publisher_id="publisher").publish_ready(
        _actor(), ORG, WORKSPACE
    )

    assert (result.claimed, result.published, result.failed) == (1, 1, 0)
    assert service.events == ["claim", "ack"]
    decoded = JobDispatchEnvelope.from_json(queue.sent[0])
    assert decoded.dispatch_id == dispatch.id

    class FailingQueue(Queue):
        def send(self, message):
            raise RuntimeError("network")

    failing_queue = FailingQueue()
    failing = DispatchService(dispatch, failing_queue)
    failed = OutboxDispatcher(failing, failing_queue, publisher_id="publisher")
    assert failed.publish_ready(_actor(), ORG, WORKSPACE).failed == 1
    assert failing.events == ["claim", "release"]


def test_send_before_ack_crash_window_leaves_duplicate_safe() -> None:
    job = _job()
    queue = Queue()
    service = DispatchService(_dispatch(job, claimed=True), queue, fail_ack=True)
    result = OutboxDispatcher(service, queue, publisher_id="publisher").publish_ready(
        _actor(), ORG, WORKSPACE
    )
    assert len(queue.sent) == 1
    assert result.acknowledgement_conflicts == 1


def test_sqs_adapter_uses_expected_parameters() -> None:
    class Client:
        def __init__(self):
            self.calls = []

        def send_message(self, **kwargs):
            self.calls.append(("send", kwargs))
            return {"MessageId": "m1"}

        def receive_message(self, **kwargs):
            self.calls.append(("receive", kwargs))
            return {
                "Messages": [
                    {
                        "Body": "{}",
                        "ReceiptHandle": "receipt",
                        "MessageId": "m1",
                        "Attributes": {"ApproximateReceiveCount": "2"},
                    }
                ]
            }

        def delete_message(self, **kwargs):
            self.calls.append(("delete", kwargs))

        def change_message_visibility(self, **kwargs):
            self.calls.append(("visibility", kwargs))

    client = Client()
    queue = Boto3SqsQueue(client, "https://sqs.example/queue")
    assert queue.send("body") == "m1"
    messages = queue.receive(max_messages=3, wait_time_seconds=20, visibility_timeout=90)
    assert messages[0].receive_count == 2
    queue.change_visibility(messages[0], 120)
    queue.delete(messages[0])
    assert client.calls[1][1]["WaitTimeSeconds"] == 20
    assert client.calls[1][1]["MaxNumberOfMessages"] == 3
    assert client.calls[2][1]["VisibilityTimeout"] == 120
    assert client.calls[3][1]["ReceiptHandle"] == "receipt"


def test_sqs_client_factory_injects_endpoint_timeouts_and_bounded_retries(
    monkeypatch,
) -> None:
    captured = {}

    def client(service_name, **kwargs):
        captured["service_name"] = service_name
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("boto3.client", client)
    create_sqs_client(
        region="eu-west-2",
        endpoint_url="http://127.0.0.1:4566",
        connect_timeout_seconds=2.0,
        read_timeout_seconds=7.0,
        max_attempts=4,
    )
    assert captured["service_name"] == "sqs"
    assert captured["region_name"] == "eu-west-2"
    assert captured["endpoint_url"] == "http://127.0.0.1:4566"
    assert captured["config"].connect_timeout == 2.0
    assert captured["config"].read_timeout == 7.0
    assert captured["config"].retries == {"max_attempts": 4, "mode": "standard"}


def test_worker_reloads_claims_executes_and_commits_before_delete() -> None:
    job = _job()
    dispatch = _dispatch(job)
    queue = Queue()
    service = JobService(job, dispatch)
    processor, handler = _processor(service, queue)
    message = QueueMessage(_envelope(job, dispatch), "receipt")

    assert processor.process(message) is MessageDisposition.DELETE
    assert service.calls == ["load", "claim", "load", "load", "complete"]
    assert handler.calls == [JobKind.INDEX_BUILD]
    assert service.job.state is JobState.SUCCEEDED


@pytest.mark.parametrize("state", [JobState.RUNNING, JobState.CANCELLED])
def test_duplicate_running_or_terminal_delivery_is_noop(state) -> None:
    job = _job(state=state)
    dispatch = _dispatch(job)
    service = JobService(job, dispatch)
    processor, handler = _processor(service, Queue())
    assert processor.process(QueueMessage(_envelope(job, dispatch), "r")) is MessageDisposition.DELETE
    assert handler.calls == []
    assert "claim" not in service.calls


def test_stale_future_and_forged_routing_messages_do_not_execute() -> None:
    job = _job(generation=2)
    dispatch = replace(_dispatch(job), dispatch_generation=1)
    service = JobService(job, dispatch)
    processor, handler = _processor(service, Queue())
    assert processor.process(QueueMessage(_envelope(job, dispatch), "r")) is MessageDisposition.DELETE

    future = _job(available_at=NOW + timedelta(minutes=5))
    future_dispatch = _dispatch(future)
    service = JobService(future, future_dispatch)
    processor, _ = _processor(service, Queue())
    assert processor.process(QueueMessage(_envelope(future, future_dispatch), "r")) is MessageDisposition.RETAIN

    service = JobService(_job(), _dispatch(_job()))
    processor, _ = _processor(service, Queue())
    forged = _envelope(service.job, service.dispatch, workspace=OTHER_WORKSPACE)
    assert processor.process(QueueMessage(forged, "r")) is MessageDisposition.DELETE
    assert handler.calls == []


def test_retry_cancellation_and_unknown_handler_commit_before_delete() -> None:
    job = _job()
    dispatch = _dispatch(job)
    service = JobService(job, dispatch)
    transient = Handler(service, "transient")
    processor, _ = _processor(service, Queue(), handler=transient)
    assert processor.process(QueueMessage(_envelope(job, dispatch), "r")) is MessageDisposition.DELETE
    assert service.job.state is JobState.PENDING
    assert service.job.dispatch_generation == 2

    job = _job()
    dispatch = _dispatch(job)
    service = JobService(job, dispatch)
    cancelling = Handler(service, "cancel")
    processor, _ = _processor(service, Queue(), handler=cancelling)
    assert processor.process(QueueMessage(_envelope(job, dispatch), "r")) is MessageDisposition.DELETE
    assert service.job.state is JobState.CANCELLED

    job = _job()
    dispatch = _dispatch(job)
    service = JobService(job, dispatch)
    processor, _ = _processor(service, Queue(), handlers={})
    assert processor.process(QueueMessage(_envelope(job, dispatch), "r")) is MessageDisposition.DELETE
    assert service.job.state is JobState.FAILED


def test_heartbeat_renews_durable_lease_before_transport_visibility() -> None:
    pending = _job()
    dispatch = _dispatch(pending)
    service = JobService(pending, dispatch)
    claimed = service.claim_job(
        _actor(), ORG, WORKSPACE, pending.id, worker_id="worker", lease_duration=timedelta(minutes=1)
    )
    queue = Queue()
    message = QueueMessage(_envelope(pending, dispatch), "receipt")
    heartbeat = WorkerHeartbeat(
        service,
        queue,
        _actor(),
        message,
        claimed,
        lease_duration=timedelta(minutes=2),
        visibility_timeout_seconds=180,
        interval_seconds=60,
        observer=type("Observer", (), {"record": lambda self, *args: None})(),
    )
    assert heartbeat.heartbeat_once()
    assert service.calls[-1] == "renew"
    assert queue.visibility == [(message, 180)]

    service.job = service.job.succeed(
        service.job.claim_token,
        JobResultReference("knowledge_index_version", service.job.subject_id),
        at=NOW,
    )
    assert not heartbeat.heartbeat_once()
    assert heartbeat.ownership_lost
    assert len(queue.visibility) == 1


def test_polling_worker_bounds_batch_isolates_failure_and_deletes_after_processing() -> None:
    queue = Queue()
    queue.received = [QueueMessage("one", "r1"), QueueMessage("two", "r2")]

    class Processor:
        def process(self, message):
            if message.body == "one":
                raise RuntimeError("poison")
            return MessageDisposition.DELETE

    worker = PollingWorker(
        queue,
        Processor(),
        WorkerRuntimeConfig(long_poll_seconds=0, receive_batch_size=10, concurrency=2),
    )
    assert worker.run_once() == 2
    assert queue.receive_kwargs["max_messages"] == 2
    assert [message.body for message in queue.deleted] == ["two"]
