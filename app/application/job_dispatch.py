"""Transactional-outbox publication without holding database locks over SQS calls."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from app.application.jobs import HostedJobService
from app.auth.context import ActorContext
from app.domain.identifiers import OrganizationId, WorkspaceId
from app.jobs.contracts import QueuePublisher
from app.jobs.envelope import JobDispatchEnvelope

logger = logging.getLogger(__name__)


class DispatchObserver(Protocol):
    def record(self, event: str, outcome: str) -> None: ...


class NoopDispatchObserver:
    def record(self, event: str, outcome: str) -> None:
        return None


@dataclass(frozen=True, slots=True)
class DispatchBatchResult:
    claimed: int
    published: int
    failed: int
    acknowledgement_conflicts: int


class OutboxDispatcher:
    def __init__(
        self,
        jobs: HostedJobService,
        publisher: QueuePublisher,
        *,
        publisher_id: str,
        batch_size: int = 10,
        claim_duration: timedelta = timedelta(seconds=30),
        observer: DispatchObserver = NoopDispatchObserver(),
    ) -> None:
        if not publisher_id.strip() or len(publisher_id) > 120:
            raise ValueError("Publisher ID is invalid")
        if not 1 <= batch_size <= 100:
            raise ValueError("Dispatcher batch size must be between 1 and 100")
        self._jobs = jobs
        self._publisher = publisher
        self._publisher_id = publisher_id
        self._batch_size = batch_size
        self._claim_duration = claim_duration
        self._observer = observer

    def publish_ready(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
    ) -> DispatchBatchResult:
        dispatches = self._jobs.claim_dispatches(
            actor,
            organization_id,
            workspace_id,
            publisher_id=self._publisher_id,
            claim_duration=self._claim_duration,
            limit=self._batch_size,
        )
        published = failed = conflicts = 0
        for dispatch in dispatches:
            if dispatch.claim_token is None:
                raise RuntimeError("Claimed dispatch is missing its claim token")
            envelope = JobDispatchEnvelope(
                job_id=dispatch.job_id,
                dispatch_id=dispatch.id,
                dispatch_generation=dispatch.dispatch_generation,
                routing_organization_id=dispatch.scope.organization_id,
                routing_workspace_id=dispatch.scope.workspace_id,
            )
            try:
                self._publisher.send(envelope.to_json())
            except Exception:
                failed += 1
                self._observer.record("outbox_publish", "failed")
                logger.exception(
                    "Outbox publish failed",
                    extra={
                        "job_id": str(dispatch.job_id),
                        "dispatch_id": str(dispatch.id),
                    },
                )
                try:
                    self._jobs.release_dispatch_claim(
                        actor,
                        organization_id,
                        workspace_id,
                        dispatch.id,
                        dispatch.claim_token,
                    )
                except Exception:
                    logger.exception(
                        "Outbox claim release failed; lease expiry will recover it",
                        extra={"dispatch_id": str(dispatch.id)},
                    )
                continue
            try:
                acknowledged = self._jobs.mark_dispatch_published(
                    actor,
                    organization_id,
                    workspace_id,
                    dispatch.id,
                    dispatch.claim_token,
                )
            except Exception:
                acknowledged = False
                logger.exception(
                    "Outbox acknowledgement failed; duplicate delivery is possible",
                    extra={"dispatch_id": str(dispatch.id)},
                )
            if acknowledged:
                published += 1
                self._observer.record("outbox_publish", "succeeded")
            else:
                conflicts += 1
                self._observer.record("outbox_publish_ack", "conflict")
                logger.warning(
                    "Published dispatch could not be acknowledged; duplicate delivery is possible",
                    extra={
                        "job_id": str(dispatch.job_id),
                        "dispatch_id": str(dispatch.id),
                    },
                )
        return DispatchBatchResult(len(dispatches), published, failed, conflicts)
