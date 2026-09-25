"""Bounded synchronous polling runtime suitable for a hosted worker process."""

from __future__ import annotations

import logging
import signal
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from app.jobs.contracts import QueueConsumer, QueueMessage
from app.application.job_dispatch import OutboxDispatcher
from app.application.jobs import HostedJobService
from app.auth.context import ActorContext
from app.domain.common import WorkspaceScope
from app.domain.identifiers import OrganizationId, WorkspaceId
from app.worker.orchestration import MessageDisposition, WorkerMessageProcessor

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WorkerRuntimeConfig:
    long_poll_seconds: int = 20
    receive_batch_size: int = 10
    initial_visibility_timeout_seconds: int = 300
    concurrency: int = 4

    def __post_init__(self) -> None:
        if not 0 <= self.long_poll_seconds <= 20:
            raise ValueError("Long-poll seconds must be between 0 and 20")
        if not 1 <= self.receive_batch_size <= 10:
            raise ValueError("Receive batch size must be between 1 and 10")
        if self.initial_visibility_timeout_seconds < 1:
            raise ValueError("Initial visibility timeout must be positive")
        if not 1 <= self.concurrency <= 64:
            raise ValueError("Worker concurrency must be between 1 and 64")


class PollingWorker:
    def __init__(
        self,
        consumer: QueueConsumer,
        processor: WorkerMessageProcessor,
        config: WorkerRuntimeConfig = WorkerRuntimeConfig(),
    ) -> None:
        self._consumer = consumer
        self._processor = processor
        self._config = config

    def run(self, stop: threading.Event | None = None) -> None:
        stop_event = stop or threading.Event()
        while not stop_event.is_set():
            self.run_once(stop_event)

    def run_once(self, stop: threading.Event | None = None) -> int:
        stop_event = stop or threading.Event()
        if stop_event.is_set():
            return 0
        messages = self._consumer.receive(
            max_messages=min(
                self._config.receive_batch_size, self._config.concurrency
            ),
            wait_time_seconds=self._config.long_poll_seconds,
            visibility_timeout=self._config.initial_visibility_timeout_seconds,
        )
        if not messages:
            return 0
        with ThreadPoolExecutor(
            max_workers=self._config.concurrency,
            thread_name_prefix="aira-worker",
        ) as executor:
            futures = {
                executor.submit(self._process_one, message): message
                for message in messages
            }
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception:
                    logger.exception("Worker message failure was isolated")
        return len(messages)

    def _process_one(self, message: QueueMessage) -> None:
        disposition = self._processor.process(message)
        if disposition is MessageDisposition.DELETE:
            try:
                self._consumer.delete(message)
            except Exception:
                logger.exception("SQS message deletion failed; duplicate is safe")


def install_shutdown_handlers(stop: threading.Event) -> None:
    def request_shutdown(signum, frame) -> None:
        del signum, frame
        stop.set()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)


class HostedWorkerRuntime:
    """Run recovery, outbox publication, and bounded consumption for known scopes."""

    def __init__(
        self,
        jobs: HostedJobService,
        dispatcher: OutboxDispatcher,
        polling_worker: PollingWorker,
        actor: ActorContext,
        scopes: tuple[WorkspaceScope, ...],
        reconciler: Callable[
            [ActorContext, OrganizationId, WorkspaceId], int
        ]
        | None = None,
    ) -> None:
        if not scopes:
            raise ValueError("Hosted worker requires at least one authorized scope")
        self._jobs = jobs
        self._dispatcher = dispatcher
        self._polling_worker = polling_worker
        self._actor = actor
        self._scopes = scopes
        self._reconciler = reconciler

    def run(self, stop: threading.Event | None = None) -> None:
        stop_event = stop or threading.Event()
        while not stop_event.is_set():
            self.run_once(stop_event)

    def run_once(self, stop: threading.Event | None = None) -> int:
        stop_event = stop or threading.Event()
        if stop_event.is_set():
            return 0
        for scope in self._scopes:
            try:
                self._jobs.recover_expired_jobs(
                    self._actor,
                    scope.organization_id,
                    scope.workspace_id,
                )
                if self._reconciler is not None:
                    self._reconciler(
                        self._actor,
                        scope.organization_id,
                        scope.workspace_id,
                    )
                self._dispatcher.publish_ready(
                    self._actor,
                    scope.organization_id,
                    scope.workspace_id,
                )
            except Exception:
                logger.exception(
                    "Worker recovery/dispatch cycle failed",
                    extra={
                        "organization_id": str(scope.organization_id),
                        "workspace_id": str(scope.workspace_id),
                    },
                )
        return self._polling_worker.run_once(stop_event)
