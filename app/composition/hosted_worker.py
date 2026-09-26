"""Explicit hosted worker composition; infrastructure supplies identity and adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.application.job_dispatch import OutboxDispatcher
from app.application.incident_context import (
    ContextCollectionPolicy,
    IncidentContextEnricher,
)
from app.application.jobs import HostedJobService, KnowledgeIndexBuildJobHandler
from app.application.triage_jobs import HostedTriageJobHandler, HostedTriageLifecycle
from app.auth.context import ActorContext
from app.authorization.service import AuthorizationService
from app.config.settings import Settings
from app.domain.common import WorkspaceScope
from app.domain.operations import JobKind
from app.jobs.sqs import Boto3SqsQueue, create_sqs_client
from app.integrations.aws import AwsRoleAssumer
from app.persistence.postgres.job_unit_of_work import PostgresJobUnitOfWork
from app.worker.orchestration import JobHandlerRegistry, WorkerMessageProcessor
from app.worker.runtime import (
    HostedWorkerRuntime,
    HostedDispatcherRuntime,
    PollingWorker,
    WorkerRuntimeConfig,
)


@dataclass(frozen=True, slots=True)
class HostedWorkerComposition:
    runtime: HostedWorkerRuntime
    polling_worker: PollingWorker
    dispatcher_runtime: HostedDispatcherRuntime
    jobs: HostedJobService
    queue: Boto3SqsQueue
    dispatcher: OutboxDispatcher


def build_incident_context_enricher(
    settings: Settings,
    role_assumer: AwsRoleAssumer,
) -> IncidentContextEnricher:
    """Build the deployment-owned bounded CloudWatch collection policy."""
    return IncidentContextEnricher(
        role_assumer,
        policy=ContextCollectionPolicy(
            metric_lookback=timedelta(
                seconds=settings.aira_context_metric_lookback_seconds
            ),
            log_lookback=timedelta(seconds=settings.aira_context_log_lookback_seconds),
            forward_window=timedelta(seconds=settings.aira_context_forward_seconds),
            max_metric_points=settings.aira_context_max_metric_points,
            max_log_events=settings.aira_context_max_log_events,
            max_log_bytes=settings.aira_context_max_log_bytes,
            max_provider_calls=settings.aira_context_max_provider_calls,
            max_context_chars=settings.aira_context_max_chars,
        ),
    )


def build_hosted_worker(
    settings: Settings,
    session_factory: sessionmaker[Session],
    authorization: AuthorizationService,
    actor: ActorContext,
    scopes: tuple[WorkspaceScope, ...],
    index_build_operation: Any,
    *,
    worker_id: str,
    publisher_id: str,
    sqs_client: Any | None = None,
    triage_handler: HostedTriageJobHandler | None = None,
    triage_lifecycle: HostedTriageLifecycle | None = None,
) -> HostedWorkerComposition:
    """Compose only injected, allowlisted hosted worker dependencies."""
    client = sqs_client or create_sqs_client(
        region=settings.aira_aws_region,
        endpoint_url=settings.aira_sqs_endpoint_url or None,
        connect_timeout_seconds=settings.aira_sqs_connect_timeout_seconds,
        read_timeout_seconds=settings.aira_sqs_read_timeout_seconds,
        max_attempts=settings.aira_sqs_max_attempts,
    )
    queue = Boto3SqsQueue(client, settings.aira_sqs_queue_url)
    jobs = HostedJobService(
        authorization,
        lambda context: PostgresJobUnitOfWork(session_factory, context),
    )
    handler = KnowledgeIndexBuildJobHandler(
        jobs,
        index_build_operation,
        lease_duration=timedelta(seconds=settings.aira_worker_job_lease_seconds),
    )
    handlers = {JobKind.INDEX_BUILD: handler}
    coordinators = {}
    if (triage_handler is None) is not (triage_lifecycle is None):
        raise ValueError("TRIAGE handler and lifecycle must be configured together")
    if triage_handler is not None and triage_lifecycle is not None:
        handlers[JobKind.TRIAGE] = triage_handler
        coordinators[JobKind.TRIAGE] = triage_lifecycle
    processor = WorkerMessageProcessor(
        jobs,
        JobHandlerRegistry(handlers, coordinators=coordinators),
        queue,
        actor,
        worker_id=worker_id,
        lease_duration=timedelta(seconds=settings.aira_worker_job_lease_seconds),
        visibility_timeout_seconds=settings.aira_sqs_visibility_timeout_seconds,
        heartbeat_interval_seconds=settings.aira_worker_heartbeat_seconds,
    )
    dispatcher = OutboxDispatcher(
        jobs,
        queue,
        publisher_id=publisher_id,
        batch_size=settings.aira_dispatcher_batch_size,
        claim_duration=timedelta(seconds=settings.aira_dispatcher_lease_seconds),
    )
    polling_worker = PollingWorker(
        queue,
        processor,
        WorkerRuntimeConfig(
            long_poll_seconds=settings.aira_sqs_long_poll_seconds,
            receive_batch_size=settings.aira_sqs_receive_batch_size,
            initial_visibility_timeout_seconds=(
                settings.aira_sqs_visibility_timeout_seconds
            ),
            concurrency=settings.aira_worker_concurrency,
        ),
    )
    runtime = HostedWorkerRuntime(
        jobs,
        dispatcher,
        polling_worker,
        actor,
        scopes,
        reconciler=(
            triage_lifecycle.reconcile_scope if triage_lifecycle is not None else None
        ),
    )
    dispatcher_runtime = HostedDispatcherRuntime(
        jobs,
        dispatcher,
        actor,
        scopes,
        reconciler=(
            triage_lifecycle.reconcile_scope if triage_lifecycle is not None else None
        ),
    )
    return HostedWorkerComposition(
        runtime,
        polling_worker,
        dispatcher_runtime,
        jobs,
        queue,
        dispatcher,
    )
