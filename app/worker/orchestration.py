"""One-message durable job orchestration, independent of the polling loop."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Callable, Protocol

from app.application.jobs import (
    ClassifiedJobExecutionError,
    HostedJobService,
    JobCancellationRequested,
    JobNotClaimable,
    JobNotFound,
    TransientJobExecutionError,
)
from app.auth.context import ActorContext
from app.authorization.service import AuthorizationDenied
from app.domain.operations import (
    JOB_TERMINAL_STATES,
    Job,
    JobErrorCategory,
    JobFailure,
    JobKind,
    JobResultReference,
    JobState,
)
from app.jobs.contracts import QueueConsumer, QueueMessage
from app.jobs.envelope import JobDispatchEnvelope, MessageEnvelopeError
from app.observability.logging import log_event
from app.observability.tracing import span

logger = logging.getLogger(__name__)


class MessageDisposition(StrEnum):
    DELETE = "delete"
    RETAIN = "retain"


class TypedJobHandler(Protocol):
    def handle(
        self,
        actor: ActorContext,
        job: Job,
        *,
        cancellation_requested: Callable[[], bool],
    ) -> JobResultReference | JobHandlerOutcome: ...


@dataclass(frozen=True, slots=True)
class JobHandlerOutcome:
    result: JobResultReference
    completion_payload: object | None = None


class JobLifecycleCoordinator(Protocol):
    def claim(
        self,
        actor: ActorContext,
        job: Job,
        *,
        worker_id: str,
        lease_duration: timedelta,
    ) -> Job: ...

    def complete(
        self, actor: ActorContext, claimed: Job, outcome: JobHandlerOutcome
    ) -> Job: ...

    def fail(
        self, actor: ActorContext, claimed: Job, failure: JobFailure
    ) -> Job: ...

    def acknowledge_cancellation(
        self, actor: ActorContext, claimed: Job
    ) -> Job: ...


class WorkerObserver(Protocol):
    def record(self, event: str, duration_ms: int, outcome: str) -> None: ...


class NoopWorkerObserver:
    def record(self, event: str, duration_ms: int, outcome: str) -> None:
        return None


class WorkerJobMetricObserver(Protocol):
    def record(
        self, event: str, duration_ms: int, outcome: str, job_type: str
    ) -> None: ...


class NoopWorkerJobMetricObserver:
    def record(
        self, event: str, duration_ms: int, outcome: str, job_type: str
    ) -> None:
        return None


class JobHandlerRegistry:
    def __init__(
        self,
        handlers: dict[JobKind, TypedJobHandler],
        *,
        coordinators: dict[JobKind, JobLifecycleCoordinator] | None = None,
    ) -> None:
        if len(handlers) != len(set(handlers)):
            raise ValueError("Duplicate job handlers are not allowed")
        self._handlers = dict(handlers)
        self._coordinators = dict(coordinators or {})
        if not set(self._coordinators).issubset(self._handlers):
            raise ValueError("Lifecycle coordinators require a registered handler")

    def get(self, kind: JobKind) -> TypedJobHandler | None:
        return self._handlers.get(kind)

    def coordinator(self, kind: JobKind) -> JobLifecycleCoordinator | None:
        return self._coordinators.get(kind)


class WorkerHeartbeat:
    def __init__(
        self,
        jobs: HostedJobService,
        consumer: QueueConsumer,
        actor: ActorContext,
        message: QueueMessage,
        job: Job,
        *,
        lease_duration: timedelta,
        visibility_timeout_seconds: int,
        interval_seconds: float,
        observer: WorkerObserver,
    ) -> None:
        if job.claim_token is None:
            raise ValueError("Heartbeat requires a claimed job")
        if interval_seconds <= 0:
            raise ValueError("Heartbeat interval must be positive")
        self._jobs = jobs
        self._consumer = consumer
        self._actor = actor
        self._message = message
        self._job = job
        self._claim_token = job.claim_token
        self._lease_duration = lease_duration
        self._visibility_timeout_seconds = visibility_timeout_seconds
        self._interval_seconds = interval_seconds
        self._observer = observer
        self._stop = threading.Event()
        self._ownership_lost = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def ownership_lost(self) -> bool:
        return self._ownership_lost.is_set()

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run,
            name=f"job-heartbeat-{self._job.id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self._interval_seconds + 1.0))

    def heartbeat_once(self) -> bool:
        started = time.monotonic()
        try:
            self._jobs.renew_job_lease(
                self._actor,
                self._job.scope.organization_id,
                self._job.scope.workspace_id,
                self._job.id,
                self._claim_token,
                lease_duration=self._lease_duration,
            )
        except Exception:
            self._ownership_lost.set()
            self._observer.record(
                "job_lease_renewal", _duration_ms(started), "failed"
            )
            logger.exception(
                "Durable job lease renewal failed",
                extra={"job_id": str(self._job.id)},
            )
            return False
        self._observer.record("job_lease_renewal", _duration_ms(started), "succeeded")
        try:
            self._consumer.change_visibility(
                self._message, self._visibility_timeout_seconds
            )
        except Exception:
            self._observer.record(
                "visibility_extension", _duration_ms(started), "failed"
            )
            logger.exception(
                "SQS visibility extension failed",
                extra={"job_id": str(self._job.id)},
            )
        else:
            self._observer.record(
                "visibility_extension", _duration_ms(started), "succeeded"
            )
        return True

    def _run(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            if not self.heartbeat_once():
                return


class WorkerMessageProcessor:
    def __init__(
        self,
        jobs: HostedJobService,
        handlers: JobHandlerRegistry,
        consumer: QueueConsumer,
        actor: ActorContext,
        *,
        worker_id: str,
        lease_duration: timedelta = timedelta(minutes=15),
        visibility_timeout_seconds: int = 300,
        heartbeat_interval_seconds: float = 60.0,
        observer: WorkerObserver = NoopWorkerObserver(),
        job_metrics: WorkerJobMetricObserver = NoopWorkerJobMetricObserver(),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not worker_id.strip() or len(worker_id) > 120:
            raise ValueError("Worker ID is invalid")
        if lease_duration <= timedelta(0):
            raise ValueError("Worker lease duration must be positive")
        if visibility_timeout_seconds < 1:
            raise ValueError("Visibility timeout must be positive")
        self._jobs = jobs
        self._handlers = handlers
        self._consumer = consumer
        self._actor = actor
        self._worker_id = worker_id
        self._lease_duration = lease_duration
        self._visibility_timeout_seconds = visibility_timeout_seconds
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._observer = observer
        self._job_metrics = job_metrics
        self._clock = clock

    def process(self, message: QueueMessage) -> MessageDisposition:
        started = time.monotonic()
        self._observer.record("sqs_message_received", 0, "received")
        try:
            envelope = JobDispatchEnvelope.from_json(message.body)
        except MessageEnvelopeError:
            self._observer.record("worker_message", _duration_ms(started), "malformed")
            logger.warning("Malformed job transport message")
            return MessageDisposition.RETAIN

        try:
            dispatch, job = self._jobs.get_execution_state(
                self._actor,
                envelope.routing_organization_id,
                envelope.routing_workspace_id,
                envelope.dispatch_id,
                envelope.job_id,
            )
        except (AuthorizationDenied, JobNotFound):
            self._observer.record("worker_message", _duration_ms(started), "unknown")
            logger.warning(
                "Unknown or unauthorized job dispatch",
                extra={
                    "job_id": str(envelope.job_id),
                    "dispatch_id": str(envelope.dispatch_id),
                },
            )
            return MessageDisposition.DELETE
        except Exception:
            self._observer.record("worker_message", _duration_ms(started), "transient")
            logger.exception(
                "Unable to load authoritative job dispatch",
                extra={
                    "job_id": str(envelope.job_id),
                    "dispatch_id": str(envelope.dispatch_id),
                },
            )
            return MessageDisposition.RETAIN

        if (
            envelope.correlation_id is not None
            and envelope.correlation_id != job.correlation.correlation_id
        ):
            self._observer.record(
                "worker_message", _duration_ms(started), "correlation_mismatch"
            )
            logger.warning(
                "Job transport correlation does not match authoritative state",
                extra={
                    "job_id": str(job.id),
                    "dispatch_id": str(dispatch.id),
                    "correlation_id": str(job.correlation.correlation_id),
                },
            )
            return MessageDisposition.RETAIN

        log_event(
            logger,
            logging.INFO,
            "job.received",
            "Durable job dispatch loaded",
            correlation_id=job.correlation.correlation_id,
            organization_id=job.scope.organization_id,
            workspace_id=job.scope.workspace_id,
            incident_id=job.correlation.incident_id,
            triage_run_id=job.correlation.triage_run_id,
            job_id=job.id,
            dispatch_id=dispatch.id,
            job_type=job.kind.value,
        )
        self._job_metrics.record(
            "job_queue_delay",
            max(0, int((self._clock() - job.created_at).total_seconds() * 1000)),
            "loaded",
            job.kind.value,
        )

        if (
            dispatch.dispatch_generation != envelope.dispatch_generation
            or job.dispatch_generation != envelope.dispatch_generation
        ):
            self._observer.record("stale_dispatch", _duration_ms(started), "ignored")
            return MessageDisposition.DELETE
        if job.state in JOB_TERMINAL_STATES:
            self._observer.record("duplicate_delivery", _duration_ms(started), "terminal")
            return MessageDisposition.DELETE
        if job.state is JobState.RUNNING:
            self._observer.record("duplicate_delivery", _duration_ms(started), "leased")
            return MessageDisposition.DELETE
        if job.available_at > self._clock():
            self._observer.record("worker_message", _duration_ms(started), "not_ready")
            return MessageDisposition.RETAIN

        handler = self._handlers.get(job.kind)
        if handler is None:
            return self._fail_without_handler(job, started)
        coordinator = self._handlers.coordinator(job.kind)

        try:
            claimed = (
                coordinator.claim(
                    self._actor,
                    job,
                    worker_id=self._worker_id,
                    lease_duration=self._lease_duration,
                )
                if coordinator is not None
                else self._jobs.claim_job(
                    self._actor,
                    job.scope.organization_id,
                    job.scope.workspace_id,
                    job.id,
                    worker_id=self._worker_id,
                    lease_duration=self._lease_duration,
                )
            )
        except JobNotClaimable:
            self._observer.record("duplicate_delivery", _duration_ms(started), "claim_lost")
            self._job_metrics.record(
                "stale_claim", _duration_ms(started), "claim_lost", job.kind.value
            )
            return self._disposition_after_claim_race(envelope)
        except Exception:
            logger.exception(
                "Durable job claim failed",
                extra={
                    "job_id": str(job.id),
                    "dispatch_id": str(dispatch.id),
                    "correlation_id": str(job.correlation.correlation_id),
                },
            )
            return MessageDisposition.RETAIN

        heartbeat = WorkerHeartbeat(
            self._jobs,
            self._consumer,
            self._actor,
            message,
            claimed,
            lease_duration=self._lease_duration,
            visibility_timeout_seconds=self._visibility_timeout_seconds,
            interval_seconds=self._heartbeat_interval_seconds,
            observer=self._observer,
        )
        heartbeat.start()
        try:
            if self._cancellation_requested(envelope):
                raise JobCancellationRequested("Job cancellation was requested")
            with span(
                "job.execute",
                **{
                    "service.name": "worker",
                    "job.type": claimed.kind.value,
                    "operation.name": "job_execute",
                },
            ):
                raw_outcome = handler.handle(
                    self._actor,
                    claimed,
                    cancellation_requested=lambda: self._cancellation_requested(envelope),
                )
            outcome = (
                raw_outcome
                if isinstance(raw_outcome, JobHandlerOutcome)
                else JobHandlerOutcome(raw_outcome)
            )
        except JobCancellationRequested:
            heartbeat.stop()
            return self._acknowledge_cancellation(claimed, started, coordinator)
        except ClassifiedJobExecutionError as exc:
            heartbeat.stop()
            return self._record_failure(
                claimed, exc.failure, started, coordinator
            )
        except TransientJobExecutionError:
            heartbeat.stop()
            return self._record_failure(
                claimed,
                JobFailure(
                    "handler_transient",
                    JobErrorCategory.TRANSIENT,
                    True,
                    "Job handler encountered a transient dependency failure",
                ),
                started,
                coordinator,
            )
        except (KeyError, TypeError, ValueError):
            heartbeat.stop()
            return self._record_failure(
                claimed,
                JobFailure(
                    "handler_validation",
                    JobErrorCategory.VALIDATION,
                    False,
                    "Persisted job payload is invalid",
                ),
                started,
                coordinator,
            )
        except Exception:
            heartbeat.stop()
            logger.exception(
                "Job handler failed",
                extra={
                    "job_id": str(claimed.id),
                    "correlation_id": str(claimed.correlation.correlation_id),
                },
            )
            return self._record_failure(
                claimed,
                JobFailure(
                    "handler_internal",
                    JobErrorCategory.INTERNAL,
                    False,
                    "Job handler failed",
                ),
                started,
                coordinator,
            )
        heartbeat.stop()
        if heartbeat.ownership_lost:
            return MessageDisposition.RETAIN
        if self._cancellation_requested(envelope):
            return self._acknowledge_cancellation(claimed, started, coordinator)
        try:
            if coordinator is not None:
                coordinator.complete(self._actor, claimed, outcome)
            else:
                self._jobs.complete_job(
                    self._actor,
                    claimed.scope.organization_id,
                    claimed.scope.workspace_id,
                    claimed.id,
                    claimed.claim_token,
                    outcome.result,
                )
        except Exception:
            if self._cancellation_requested(envelope):
                return self._acknowledge_cancellation(claimed, started, coordinator)
            logger.exception(
                "Durable job completion failed",
                extra={
                    "job_id": str(claimed.id),
                    "correlation_id": str(claimed.correlation.correlation_id),
                },
            )
            return MessageDisposition.RETAIN
        self._observer.record("worker_job", _duration_ms(started), "succeeded")
        self._job_metrics.record(
            "jobs_succeeded", _duration_ms(started), "succeeded", job.kind.value
        )
        log_event(
            logger,
            logging.INFO,
            "job.succeeded",
            "Durable job completed",
            correlation_id=job.correlation.correlation_id,
            incident_id=job.correlation.incident_id,
            triage_run_id=job.correlation.triage_run_id,
            job_id=job.id,
            dispatch_id=dispatch.id,
            job_type=job.kind.value,
            duration_ms=_duration_ms(started),
        )
        return MessageDisposition.DELETE

    def _fail_without_handler(
        self, job: Job, started: float
    ) -> MessageDisposition:
        try:
            claimed = self._jobs.claim_job(
                self._actor,
                job.scope.organization_id,
                job.scope.workspace_id,
                job.id,
                worker_id=self._worker_id,
                lease_duration=self._lease_duration,
            )
        except JobNotClaimable:
            return MessageDisposition.DELETE
        except Exception:
            return MessageDisposition.RETAIN
        return self._record_failure(
            claimed,
            JobFailure(
                "unknown_job_kind",
                JobErrorCategory.CONFIGURATION,
                False,
                "No allowlisted handler is configured for this job type",
            ),
            started,
        )

    def _record_failure(
        self,
        claimed: Job,
        failure: JobFailure,
        started: float,
        coordinator: JobLifecycleCoordinator | None = None,
    ) -> MessageDisposition:
        try:
            updated = (
                coordinator.fail(self._actor, claimed, failure)
                if coordinator is not None
                else self._jobs.fail_job(
                    self._actor,
                    claimed.scope.organization_id,
                    claimed.scope.workspace_id,
                    claimed.id,
                    claimed.claim_token,
                    failure,
                )
            )
        except Exception:
            logger.exception(
                "Durable job failure transition failed",
                extra={
                    "job_id": str(claimed.id),
                    "correlation_id": str(claimed.correlation.correlation_id),
                },
            )
            return MessageDisposition.RETAIN
        outcome = "retry" if updated.state is JobState.PENDING else "failed"
        self._observer.record("worker_job", _duration_ms(started), outcome)
        event = "jobs_retried" if updated.state is JobState.PENDING else "jobs_failed"
        self._job_metrics.record(
            event, _duration_ms(started), outcome, claimed.kind.value
        )
        return MessageDisposition.DELETE

    def _acknowledge_cancellation(
        self,
        claimed: Job,
        started: float,
        coordinator: JobLifecycleCoordinator | None = None,
    ) -> MessageDisposition:
        try:
            if coordinator is not None:
                coordinator.acknowledge_cancellation(self._actor, claimed)
            else:
                self._jobs.acknowledge_cancellation(
                    self._actor,
                    claimed.scope.organization_id,
                    claimed.scope.workspace_id,
                    claimed.id,
                    claimed.claim_token,
                )
        except Exception:
            logger.exception(
                "Durable job cancellation acknowledgement failed",
                extra={
                    "job_id": str(claimed.id),
                    "correlation_id": str(claimed.correlation.correlation_id),
                },
            )
            return MessageDisposition.RETAIN
        self._observer.record("worker_job", _duration_ms(started), "cancelled")
        self._job_metrics.record(
            "jobs_cancelled", _duration_ms(started), "cancelled", claimed.kind.value
        )
        return MessageDisposition.DELETE

    def _cancellation_requested(self, envelope: JobDispatchEnvelope) -> bool:
        try:
            _, current = self._jobs.get_execution_state(
                self._actor,
                envelope.routing_organization_id,
                envelope.routing_workspace_id,
                envelope.dispatch_id,
                envelope.job_id,
            )
        except Exception:
            return False
        return current.cancellation_requested_at is not None

    def _disposition_after_claim_race(
        self, envelope: JobDispatchEnvelope
    ) -> MessageDisposition:
        try:
            _, current = self._jobs.get_execution_state(
                self._actor,
                envelope.routing_organization_id,
                envelope.routing_workspace_id,
                envelope.dispatch_id,
                envelope.job_id,
            )
        except Exception:
            return MessageDisposition.RETAIN
        if current.state in JOB_TERMINAL_STATES or current.state is JobState.RUNNING:
            return MessageDisposition.DELETE
        return MessageDisposition.RETAIN


def _duration_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))
