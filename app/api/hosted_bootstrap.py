"""Authenticated identity and authorized-scope bootstrap for the hosted web BFF."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.application.bootstrap import HostedBootstrapService
from app.auth.context import ActorContext
from app.authorization.service import AuthorizationDenied


class BootstrapWorkspaceResponse(BaseModel):
    workspace_id: str
    name: str
    slug: str


class BootstrapOrganizationResponse(BaseModel):
    organization_id: str
    name: str
    slug: str
    role: str
    permissions: list[str]
    workspaces: list[BootstrapWorkspaceResponse]


class HostedBootstrapResponse(BaseModel):
    user_id: str
    organizations: list[BootstrapOrganizationResponse]


def build_hosted_bootstrap_router(
    service: HostedBootstrapService,
    actor_dependency,
) -> APIRouter:
    router = APIRouter(prefix="/v3", tags=["hosted-bootstrap"])

    @router.get("/me", response_model=HostedBootstrapResponse)
    def get_me(
        actor: ActorContext = Depends(actor_dependency),
    ) -> HostedBootstrapResponse:
        try:
            bootstrap = service.get(actor)
        except (AuthorizationDenied, PermissionError) as exc:
            raise HTTPException(status_code=403, detail="Access denied") from exc
        return HostedBootstrapResponse(
            user_id=bootstrap.user_id,
            organizations=[
                BootstrapOrganizationResponse(
                    organization_id=organization.id,
                    name=organization.name,
                    slug=organization.slug,
                    role=organization.role,
                    permissions=list(organization.permissions),
                    workspaces=[
                        BootstrapWorkspaceResponse(
                            workspace_id=workspace.id,
                            name=workspace.name,
                            slug=workspace.slug,
                        )
                        for workspace in organization.workspaces
                    ],
                )
                for organization in bootstrap.organizations
            ],
        )

    return router
