"""Hosted organization-scoped workspace management routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.application.workspaces import (
    HostedWorkspaceService,
    WorkspaceConflict,
    WorkspaceListCursor,
    WorkspaceNotFound,
    WorkspaceVersionConflict,
)
from app.auth.context import ActorContext
from app.authorization.service import AuthorizationDenied
from app.domain.identifiers import OrganizationId, WorkspaceId
from app.domain.tenancy import Workspace, WorkspaceConfiguration
from app.security.cursors import CursorCodec, InvalidCursor


class WorkspaceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)


class WorkspaceMetadataUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def require_update(self) -> WorkspaceMetadataUpdateRequest:
        if not self.model_fields_set.intersection({"name", "slug", "description"}):
            raise ValueError("Workspace metadata update cannot be empty")
        return self


class WorkspaceConfigurationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    rag_top_k: int | None = Field(default=None, ge=1, le=64)
    llm_temperature: float | None = Field(default=None, ge=0, le=2)

    @model_validator(mode="after")
    def require_update(self) -> WorkspaceConfigurationUpdateRequest:
        if self.rag_top_k is None and self.llm_temperature is None:
            raise ValueError("Workspace configuration update cannot be empty")
        return self


class WorkspaceArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)


class WorkspaceSummaryResponse(BaseModel):
    workspace_id: str
    organization_id: str
    name: str
    slug: str
    description: str | None
    state: str
    version: int
    created_at: datetime
    updated_at: datetime


class WorkspaceConfigurationResponse(BaseModel):
    schema_version: int
    version: int
    rag_top_k: int
    llm_temperature: float
    updated_at: datetime


class WorkspaceDetailResponse(BaseModel):
    workspace: WorkspaceSummaryResponse
    configuration: WorkspaceConfigurationResponse


class WorkspacePageResponse(BaseModel):
    items: list[WorkspaceSummaryResponse]
    next_cursor: str | None = None


def build_hosted_workspace_router(
    service: HostedWorkspaceService,
    actor_dependency,
    *,
    cursor_codec: CursorCodec,
) -> APIRouter:
    router = APIRouter(
        prefix="/v3/organizations/{organization_id}/workspaces",
        tags=["hosted-workspaces"],
    )

    @router.get("", response_model=WorkspacePageResponse)
    def list_workspaces(
        organization_id: str,
        actor: ActorContext = Depends(actor_dependency),
        limit: int = Query(50, ge=1, le=100),
        cursor: str | None = None,
    ) -> WorkspacePageResponse:
        try:
            organization = OrganizationId(organization_id)
            page = service.list_visible_page(
                actor,
                organization,
                limit=limit,
                before=(
                    _decode_cursor(cursor_codec, cursor, organization)
                    if cursor
                    else None
                ),
            )
            return WorkspacePageResponse(
                items=[_workspace_response(item) for item in page.items],
                next_cursor=(
                    _encode_cursor(cursor_codec, page.next_cursor, organization)
                    if page.next_cursor
                    else None
                ),
            )
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post(
        "", response_model=WorkspaceDetailResponse, status_code=status.HTTP_201_CREATED
    )
    def create_workspace(
        organization_id: str,
        body: WorkspaceCreateRequest,
        actor: ActorContext = Depends(actor_dependency),
    ) -> WorkspaceDetailResponse:
        try:
            workspace = service.create(
                actor,
                OrganizationId(organization_id),
                name=body.name,
                slug=body.slug,
                description=body.description,
            )
            configuration = service.get_configuration(
                actor, workspace.organization_id, workspace.id
            )
            return _detail_response(workspace, configuration)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get("/{workspace_id}", response_model=WorkspaceDetailResponse)
    def get_workspace(
        organization_id: str,
        workspace_id: str,
        actor: ActorContext = Depends(actor_dependency),
    ) -> WorkspaceDetailResponse:
        try:
            organization = OrganizationId(organization_id)
            workspace = service.get(actor, organization, WorkspaceId(workspace_id))
            configuration = service.get_configuration(actor, organization, workspace.id)
            return _detail_response(workspace, configuration)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.patch("/{workspace_id}", response_model=WorkspaceDetailResponse)
    def update_workspace(
        organization_id: str,
        workspace_id: str,
        body: WorkspaceMetadataUpdateRequest,
        actor: ActorContext = Depends(actor_dependency),
    ) -> WorkspaceDetailResponse:
        try:
            organization = OrganizationId(organization_id)
            updates: dict[str, Any] = {}
            if "name" in body.model_fields_set:
                updates["name"] = body.name
            if "slug" in body.model_fields_set:
                updates["slug"] = body.slug
            if "description" in body.model_fields_set:
                updates["description"] = body.description
            workspace = service.update_metadata(
                actor,
                organization,
                WorkspaceId(workspace_id),
                expected_version=body.expected_version,
                **updates,
            )
            configuration = service.get_configuration(actor, organization, workspace.id)
            return _detail_response(workspace, configuration)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.patch("/{workspace_id}/configuration", response_model=WorkspaceDetailResponse)
    def update_configuration(
        organization_id: str,
        workspace_id: str,
        body: WorkspaceConfigurationUpdateRequest,
        actor: ActorContext = Depends(actor_dependency),
    ) -> WorkspaceDetailResponse:
        try:
            organization = OrganizationId(organization_id)
            workspace = service.get(actor, organization, WorkspaceId(workspace_id))
            patch: dict[str, Any] = body.model_dump(
                exclude={"expected_version"}, exclude_none=True
            )
            configuration = service.update_configuration(
                actor,
                organization,
                workspace.id,
                patch,
                expected_version=body.expected_version,
            )
            return _detail_response(workspace, configuration)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post("/{workspace_id}/archive", response_model=WorkspaceSummaryResponse)
    def archive_workspace(
        organization_id: str,
        workspace_id: str,
        body: WorkspaceArchiveRequest,
        actor: ActorContext = Depends(actor_dependency),
    ) -> WorkspaceSummaryResponse:
        try:
            workspace = service.archive(
                actor,
                OrganizationId(organization_id),
                WorkspaceId(workspace_id),
                expected_version=body.expected_version,
            )
            return _workspace_response(workspace)
        except Exception as exc:
            raise _http_error(exc) from exc

    return router


def _workspace_response(workspace: Workspace) -> WorkspaceSummaryResponse:
    return WorkspaceSummaryResponse(
        workspace_id=str(workspace.id),
        organization_id=str(workspace.organization_id),
        name=workspace.name,
        slug=workspace.slug,
        description=workspace.description,
        state=workspace.state.value,
        version=workspace.version,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
    )


def _detail_response(
    workspace: Workspace, configuration: WorkspaceConfiguration
) -> WorkspaceDetailResponse:
    return WorkspaceDetailResponse(
        workspace=_workspace_response(workspace),
        configuration=WorkspaceConfigurationResponse(
            schema_version=configuration.schema_version,
            version=configuration.version,
            rag_top_k=configuration.rag_top_k,
            llm_temperature=configuration.llm_temperature,
            updated_at=configuration.updated_at,
        ),
    )


def _encode_cursor(
    codec: CursorCodec,
    cursor: WorkspaceListCursor,
    organization_id: OrganizationId,
) -> str:
    return codec.encode(
        kind="workspaces",
        scope={"organization_id": str(organization_id)},
        values={
            "created_at": cursor.created_at.isoformat(),
            "workspace_id": str(cursor.workspace_id),
        },
    )


def _decode_cursor(
    codec: CursorCodec,
    value: str,
    organization_id: OrganizationId,
) -> WorkspaceListCursor:
    try:
        values = codec.decode(
            value,
            kind="workspaces",
            scope={"organization_id": str(organization_id)},
        )
        parsed = datetime.fromisoformat(values["created_at"])
        if parsed.tzinfo is None:
            raise ValueError
        return WorkspaceListCursor(parsed, WorkspaceId(values["workspace_id"]))
    except (InvalidCursor, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=422, detail="Invalid workspace cursor") from exc


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, AuthorizationDenied):
        return HTTPException(status_code=403, detail="Access denied")
    if isinstance(exc, WorkspaceNotFound):
        return HTTPException(status_code=404, detail="Workspace not found")
    if isinstance(exc, WorkspaceVersionConflict):
        return HTTPException(status_code=409, detail="Workspace version is stale")
    if isinstance(exc, WorkspaceConflict):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail="Invalid resource identifier")
    return HTTPException(status_code=500, detail="Workspace operation failed")
