"""Explicit hosted FastAPI composition, separate from the Version 2 app."""

from __future__ import annotations

from fastapi import FastAPI

from app.api.hosted_alert_ingestion import build_hosted_alert_ingestion_router
from app.api.hosted_bootstrap import build_hosted_bootstrap_router
from app.api.hosted_aws_integrations import build_hosted_aws_integration_router
from app.api.hosted_incidents import build_hosted_incident_router
from app.api.hosted_workspaces import build_hosted_workspace_router
from app.application.bootstrap import HostedBootstrapService
from app.application.alert_ingestion import HostedAlertIngestionService
from app.application.aws_integrations import HostedAwsIntegrationService
from app.application.incidents import HostedIncidentService
from app.application.actions import HostedActionProposalService
from app.application.approvals import HostedApprovalService
from app.application.workspaces import HostedWorkspaceService


def build_hosted_api(
    incidents: HostedIncidentService,
    actor_dependency,
    bootstrap: HostedBootstrapService | None = None,
    workspaces: HostedWorkspaceService | None = None,
    aws_integrations: HostedAwsIntegrationService | None = None,
    alert_ingestion: HostedAlertIngestionService | None = None,
    machine_actor_dependency=None,
    action_proposals: HostedActionProposalService | None = None,
    approvals: HostedApprovalService | None = None,
) -> FastAPI:
    application = FastAPI(
        title="AIRA Hosted API",
        version="3",
        description="Tenant-authorized durable incident and asynchronous triage API.",
    )
    application.include_router(
        build_hosted_incident_router(
            incidents,
            actor_dependency,
            action_proposals=action_proposals,
            approvals=approvals,
        )
    )
    if bootstrap is not None:
        application.include_router(
            build_hosted_bootstrap_router(bootstrap, actor_dependency)
        )
    if workspaces is not None:
        application.include_router(
            build_hosted_workspace_router(workspaces, actor_dependency)
        )
    if aws_integrations is not None:
        application.include_router(
            build_hosted_aws_integration_router(aws_integrations, actor_dependency)
        )
    if alert_ingestion is not None:
        if machine_actor_dependency is None:
            raise ValueError("Hosted alert ingestion requires machine authentication")
        application.include_router(
            build_hosted_alert_ingestion_router(
                alert_ingestion, machine_actor_dependency
            )
        )
    return application
