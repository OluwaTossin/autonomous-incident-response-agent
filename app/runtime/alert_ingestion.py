"""EventBridge-to-SQS alert receiver with deployment-owned tenant routing."""

from __future__ import annotations

import json
import logging
import threading

from pydantic import ValidationError

from app.api.hosted_alert_ingestion import EventBridgeAlarmEnvelope
from app.application.alert_ingestion import HostedAlertIngestionService
from app.auth.context import trusted_system_actor
from app.authorization.permissions import Permission
from app.authorization.service import AuthorizationService, SystemAuthorizationGrant
from app.config.settings import Settings
from app.domain.identifiers import IntegrationId
from app.jobs.sqs import Boto3SqsQueue, create_sqs_client
from app.persistence.postgres.alert_ingestion import PostgresAlertIngestionUnitOfWork
from app.persistence.postgres.authorization import (
    PostgresAuthorizationFactsRepository,
    PostgresTenantResourceValidator,
)
from app.persistence.postgres.engine import create_postgres_engine, create_session_factory
from app.runtime.config import alert_routes, validate_hosted_settings
from app.worker.runtime import install_shutdown_handlers

logger = logging.getLogger(__name__)


def run_alert_ingestion(settings: Settings) -> None:
    validate_hosted_settings(settings, worker=True)
    if not settings.aira_alert_queue_url:
        raise RuntimeError("AIRA_ALERT_QUEUE_URL is required")
    routes = alert_routes(settings)
    engine = create_postgres_engine(settings.aira_database_url)
    sessions = create_session_factory(engine)
    actor = trusted_system_actor(
        system_name="alert-ingress",
        workload_issuer="aws:iam",
        workload_subject=settings.aira_workload_subject,
    )
    permissions = frozenset(
        {
            Permission.INCIDENT_CREATE,
            Permission.INTEGRATION_READ,
            Permission.TRIAGE_RUN,
            Permission.JOB_CREATE,
        }
    )
    authorization = AuthorizationService(
        PostgresAuthorizationFactsRepository(sessions),
        PostgresTenantResourceValidator(sessions),
        system_grants=tuple(
            SystemAuthorizationGrant(
                "alert-ingress",
                "aws:iam",
                settings.aira_workload_subject,
                route.scope.organization_id,
                permissions,
                frozenset({route.scope.workspace_id}),
            )
            for route in routes
        ),
    )
    service = HostedAlertIngestionService(
        authorization,
        lambda context: PostgresAlertIngestionUnitOfWork(sessions, context),
    )
    queue = Boto3SqsQueue(
        create_sqs_client(
            region=settings.aira_aws_region,
            connect_timeout_seconds=settings.aira_sqs_connect_timeout_seconds,
            read_timeout_seconds=settings.aira_sqs_read_timeout_seconds,
            max_attempts=settings.aira_sqs_max_attempts,
        ),
        settings.aira_alert_queue_url,
    )
    stop = threading.Event()
    install_shutdown_handlers(stop)
    while not stop.is_set():
        for message in queue.receive(
            max_messages=min(10, settings.aira_sqs_receive_batch_size),
            wait_time_seconds=settings.aira_sqs_long_poll_seconds,
            visibility_timeout=120,
        ):
            try:
                envelope = EventBridgeAlarmEnvelope.model_validate(json.loads(message.body))
                route = next(
                    route
                    for route in routes
                    if route.aws_account_id == envelope.account
                    and envelope.region in route.regions
                )
                service.ingest(
                    actor,
                    route.scope.organization_id,
                    route.scope.workspace_id,
                    IntegrationId(route.integration_id),
                    envelope.to_domain(),
                )
            except (StopIteration, ValidationError, ValueError, json.JSONDecodeError):
                logger.exception("Alert delivery rejected; SQS retry/DLQ remains authoritative")
                continue
            except Exception:
                logger.exception("Alert ingestion failed; message remains visible for retry")
                continue
            queue.delete(message)
