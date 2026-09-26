"""Authorized hosted usage and quota summary API."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.application.usage import HostedUsageService
from app.auth.context import ActorContext
from app.authorization.service import AuthorizationDenied
from app.domain.identifiers import OrganizationId, WorkspaceId


class QuotaSummaryResponse(BaseModel):
    quota_type: str
    status: str
    current: int
    limit: int
    remaining: int
    reset_at: datetime | None
    policy_version: int


class UsageSummaryResponse(BaseModel):
    organization_id: str
    workspace_id: str
    generated_at: datetime
    quotas: list[QuotaSummaryResponse]
    billing_enabled: bool = False


def build_hosted_usage_router(service: HostedUsageService, actor_dependency) -> APIRouter:
    router = APIRouter(
        prefix="/v3/organizations/{organization_id}/workspaces/{workspace_id}/usage",
        tags=["hosted-usage"],
    )

    @router.get("", response_model=UsageSummaryResponse)
    def workspace_usage(
        organization_id: str,
        workspace_id: str,
        actor: ActorContext = Depends(actor_dependency),
    ) -> UsageSummaryResponse:
        try:
            summary = service.workspace_summary(
                actor, OrganizationId(organization_id), WorkspaceId(workspace_id)
            )
        except AuthorizationDenied as exc:
            raise HTTPException(
                403, detail={"code": "forbidden", "message": "Access denied"}
            ) from exc
        return UsageSummaryResponse(
            organization_id=str(summary.organization_id),
            workspace_id=str(summary.workspace_id),
            generated_at=summary.generated_at,
            quotas=[
                QuotaSummaryResponse(
                    quota_type=item.quota_type.value,
                    status=item.status.value,
                    current=item.current,
                    limit=item.limit,
                    remaining=item.remaining,
                    reset_at=item.reset_at,
                    policy_version=item.policy_version,
                )
                for item in summary.quotas
            ],
        )

    return router
