"""Explicit hosted FastAPI composition, separate from the Version 2 app."""

from __future__ import annotations

from fastapi import FastAPI

from app.api.hosted_incidents import build_hosted_incident_router
from app.application.incidents import HostedIncidentService


def build_hosted_api(
    incidents: HostedIncidentService,
    actor_dependency,
) -> FastAPI:
    application = FastAPI(
        title="AIRA Hosted API",
        version="3",
        description="Tenant-authorized durable incident and asynchronous triage API.",
    )
    application.include_router(
        build_hosted_incident_router(incidents, actor_dependency)
    )
    return application
