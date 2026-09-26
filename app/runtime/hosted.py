"""Production entrypoints for hosted API and worker processes."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import boto3
import uvicorn
from sqlalchemy import text

from app.application.actions import HostedActionProposalService
from app.application.alert_ingestion import HostedAlertIngestionService
from app.application.approvals import HostedApprovalService
from app.application.aws_integrations import HostedAwsIntegrationService
from app.application.bootstrap import HostedBootstrapService
from app.application.execution_intents import HostedExecutionIntentService
from app.application.governance import OrganizationGovernanceService
from app.application.incidents import HostedIncidentService
from app.application.knowledge_bundles import HostedKnowledgeBundleService
from app.application.triage_jobs import HostedTriageJobHandler, HostedTriageLifecycle
from app.application.workspaces import HostedWorkspaceService
from app.auth.context import trusted_system_actor
from app.authorization.permissions import Permission
from app.authorization.service import (
    AuthorizationService,
    SystemAuthorizationGrant,
)
from app.composition.hosted_api import build_hosted_api
from app.composition.hosted_identity import build_hosted_actor_dependency
from app.composition.hosted_worker import (
    build_hosted_worker,
    build_incident_context_enricher,
)
from app.config.settings import Settings, get_settings
from app.integrations.aws import Boto3AwsRoleAssumer
from app.documents.s3 import S3DocumentStorageConfig, create_s3_client
from app.knowledge.bundle import HostedKnowledgeBundleBuilder
from app.knowledge.cache import CachedHostedFaissRetriever, VerifiedBundleCache
from app.knowledge.s3 import S3ImmutableObjectStorage
from app.knowledge.storage import KnowledgeBundlePublisher
from app.persistence.postgres.alert_ingestion import PostgresAlertIngestionUnitOfWork
from app.persistence.postgres.authorization import (
    PostgresAuthorizationFactsRepository,
    PostgresTenantResourceValidator,
)
from app.persistence.postgres.aws_integrations import PostgresAwsIntegrationUnitOfWork
from app.persistence.postgres.engine import create_postgres_engine, create_session_factory
from app.persistence.postgres.governance_unit_of_work import PostgresGovernanceUnitOfWork
from app.persistence.postgres.incident_unit_of_work import PostgresHostedIncidentUnitOfWork
from app.persistence.postgres.knowledge import PostgresHostedKnowledgeRepository
from app.persistence.postgres.knowledge_sources import PostgresKnowledgeSourceContentReader
from app.persistence.postgres.workspace_unit_of_work import PostgresWorkspaceUnitOfWork
from app.runtime.config import validate_hosted_settings, worker_scopes
from app.runtime.alert_ingestion import run_alert_ingestion
from app.worker.entrypoint import run_dispatcher, run_polling_worker

logger = logging.getLogger(__name__)


def create_api(settings: Settings | None = None):
    settings = settings or get_settings()
    validate_hosted_settings(settings)
    engine = create_postgres_engine(settings.aira_database_url)
    sessions = create_session_factory(engine)
    authorization = AuthorizationService(
        PostgresAuthorizationFactsRepository(sessions),
        PostgresTenantResourceValidator(sessions),
    )
    actor_dependency = build_hosted_actor_dependency(settings, sessions)
    def incident_uow(context):
        return PostgresHostedIncidentUnitOfWork(sessions, context)

    def workspace_uow(context):
        return PostgresWorkspaceUnitOfWork(sessions, context)

    def governance_uow(context):
        return PostgresGovernanceUnitOfWork(sessions, context)

    def integration_uow(context):
        return PostgresAwsIntegrationUnitOfWork(sessions, context)

    def alert_uow(context):
        return PostgresAlertIngestionUnitOfWork(sessions, context)

    workspaces = HostedWorkspaceService(authorization, workspace_uow)
    governance = OrganizationGovernanceService(authorization, governance_uow)
    actions = HostedActionProposalService(authorization, incident_uow)
    approvals = HostedApprovalService(authorization, incident_uow)
    execution_intents = HostedExecutionIntentService(authorization, incident_uow)
    role_assumer = Boto3AwsRoleAssumer(
        boto3.client("sts", region_name=settings.aira_aws_region),
        source_role_arn=settings.aira_aws_source_role_arn,
    )

    def readiness() -> None:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    application = build_hosted_api(
        HostedIncidentService(authorization, incident_uow),
        actor_dependency,
        bootstrap=HostedBootstrapService(authorization, governance, workspaces),
        workspaces=workspaces,
        aws_integrations=HostedAwsIntegrationService(
            authorization,
            integration_uow,
            role_assumer,
            trusted_principal_arn=settings.aira_aws_trusted_principal_arn,
        ),
        alert_ingestion=HostedAlertIngestionService(authorization, alert_uow),
        machine_actor_dependency=actor_dependency,
        action_proposals=actions,
        approvals=approvals,
        execution_intents=execution_intents,
        readiness_check=readiness,
    )
    application.state.database_engine = engine
    return application


def _configure_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _serve_api() -> None:
    application = create_api()
    uvicorn.run(
        application,
        host="0.0.0.0",
        port=8000,
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("AIRA_TRUSTED_PROXY_IPS", "10.0.0.0/8"),
        server_header=False,
    )


def create_worker(settings: Settings | None = None):
    settings = settings or get_settings()
    scopes = worker_scopes(settings)
    engine = create_postgres_engine(settings.aira_database_url)
    sessions = create_session_factory(engine)
    permissions = frozenset(
        {
            Permission.ACTION_PROPOSE,
            Permission.INTEGRATION_READ,
            Permission.JOB_CREATE,
            Permission.JOB_EXECUTE,
            Permission.KNOWLEDGE_MANAGE,
            Permission.KNOWLEDGE_READ,
            Permission.TRIAGE_RUN,
        }
    )
    grants = tuple(
        SystemAuthorizationGrant(
            "aira-worker",
            "aws:iam",
            settings.aira_workload_subject,
            scope.organization_id,
            permissions,
            frozenset({scope.workspace_id}),
        )
        for scope in scopes
    )
    actor = trusted_system_actor(
        system_name="aira-worker",
        workload_issuer="aws:iam",
        workload_subject=settings.aira_workload_subject,
    )
    authorization = AuthorizationService(
        PostgresAuthorizationFactsRepository(sessions),
        PostgresTenantResourceValidator(sessions),
        system_grants=grants,
    )
    def incident_uow(context):
        return PostgresHostedIncidentUnitOfWork(sessions, context)
    role_assumer = Boto3AwsRoleAssumer(
        boto3.client("sts", region_name=settings.aira_aws_region),
        source_role_arn=settings.aira_aws_source_role_arn,
    )
    document_config = S3DocumentStorageConfig(
        settings.aira_document_bucket,
        settings.aira_aws_region,
        settings.aira_kms_key_arn,
    )
    knowledge_config = S3DocumentStorageConfig(
        settings.aira_knowledge_bucket,
        settings.aira_aws_region,
        settings.aira_kms_key_arn,
    )
    document_storage = S3ImmutableObjectStorage(
        create_s3_client(document_config), document_config
    )
    knowledge_storage = S3ImmutableObjectStorage(
        create_s3_client(knowledge_config), knowledge_config
    )
    repository = PostgresHostedKnowledgeRepository(sessions)
    builder = HostedKnowledgeBundleBuilder(
        PostgresKnowledgeSourceContentReader(sessions, document_storage),
        embedding_model=settings.embedding_model,
    )
    publisher = KnowledgeBundlePublisher(knowledge_storage)
    knowledge = HostedKnowledgeBundleService(
        authorization, repository, builder, publisher
    )
    actions = HostedActionProposalService(authorization, incident_uow)
    lifecycle = HostedTriageLifecycle(
        authorization, incident_uow, proposal_generator=actions
    )
    cache = VerifiedBundleCache(Path("/tmp/aira-faiss-cache"), knowledge_storage)

    def top_k(actor_context, organization_id, workspace_id) -> int:
        context = authorization.authorize(
            actor_context,
            organization_id,
            Permission.KNOWLEDGE_READ,
            workspace_id=workspace_id,
        )
        with PostgresWorkspaceUnitOfWork(sessions, context) as uow:
            configuration = uow.workspace_configurations.get(workspace_id)
            if configuration is None:
                raise RuntimeError("Workspace configuration is unavailable")
            return configuration.rag_top_k

    triage_handler = HostedTriageJobHandler(
        lifecycle,
        knowledge,
        CachedHostedFaissRetriever(cache),
        top_k,
        context_enricher=build_incident_context_enricher(settings, role_assumer),
    )
    return build_hosted_worker(
        settings,
        sessions,
        authorization,
        actor,
        scopes,
        knowledge,
        worker_id=os.environ.get("HOSTNAME", "aira-worker")[:120],
        publisher_id=f"dispatcher-{os.getpid()}",
        triage_handler=triage_handler,
        triage_lifecycle=lifecycle,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="AIRA hosted runtime")
    parser.add_argument("process", choices=("api", "worker", "dispatcher", "alert-ingestion"))
    args = parser.parse_args(argv)
    _configure_logging()
    if args.process == "api":
        _serve_api()
        return
    if args.process == "worker":
        composition = create_worker()
        run_polling_worker(composition.polling_worker)
    elif args.process == "dispatcher":
        composition = create_worker()
        run_dispatcher(composition.dispatcher_runtime)
    else:
        run_alert_ingestion(get_settings())


if __name__ == "__main__":
    main()
