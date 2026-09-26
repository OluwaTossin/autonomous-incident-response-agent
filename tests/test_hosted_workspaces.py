"""Hosted workspace HTTP contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.hosted_workspaces import build_hosted_workspace_router
from app.application.workspaces import (
    WorkspaceListCursor,
    WorkspaceNotFound,
    WorkspacePage,
    WorkspaceVersionConflict,
)
from app.auth.context import ActorContext, AuthenticationMethod
from app.authorization.service import AuthorizationDenied
from app.domain.common import ActorKind, ActorReference, WorkspaceScope
from app.domain.identifiers import OrganizationId, UserId, WorkspaceId
from app.domain.tenancy import (
    WORKSPACE_CONFIG_SCHEMA_VERSION,
    Workspace,
    WorkspaceConfiguration,
)
from app.security.cursors import CursorCodec

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
ORG = OrganizationId("00000000-0000-4000-8000-000000000001")
WORKSPACE = WorkspaceId("00000000-0000-4000-8000-000000000002")
CURSORS = CursorCodec("test-cursor-signing-key-at-least-32-bytes")
ACTOR = ActorReference(
    ActorKind.HUMAN,
    actor_id=UserId("00000000-0000-4000-8000-000000000003"),
)


def _actor() -> ActorContext:
    return ActorContext(
        ACTOR,
        AuthenticationMethod.OIDC,
        issuer="https://issuer.example",
        external_subject="owner",
    )


def _workspace(*, version: int = 1) -> Workspace:
    return Workspace(
        id=WORKSPACE,
        organization_id=ORG,
        name="Production",
        slug="production",
        description="Production operations",
        version=version,
        created_by=ACTOR,
        created_at=NOW,
        updated_at=NOW,
    )


def _configuration(*, version: int = 1) -> WorkspaceConfiguration:
    return WorkspaceConfiguration(
        scope=WorkspaceScope(ORG, WORKSPACE),
        schema_version=WORKSPACE_CONFIG_SCHEMA_VERSION,
        version=version,
        rag_top_k=8,
        llm_temperature=0.2,
        updated_by=ACTOR,
        created_at=NOW,
        updated_at=NOW,
    )


class WorkspaceService:
    def __init__(self) -> None:
        self.workspace = _workspace()
        self.configuration = _configuration()

    def list_visible_page(self, actor, organization_id, *, limit, before=None):
        if organization_id != ORG:
            raise AuthorizationDenied("Access denied")
        assert actor == _actor()
        assert 1 <= limit <= 100
        return WorkspacePage((self.workspace,), None)

    def create(self, actor, organization_id, **values):
        assert actor == _actor() and organization_id == ORG
        self.workspace = _workspace()
        return self.workspace

    def get(self, actor, organization_id, workspace_id):
        if organization_id != ORG:
            raise AuthorizationDenied("Access denied")
        if workspace_id != WORKSPACE:
            raise WorkspaceNotFound("Workspace not found")
        return self.workspace

    def get_configuration(self, actor, organization_id, workspace_id):
        self.get(actor, organization_id, workspace_id)
        return self.configuration

    def update_metadata(self, actor, organization_id, workspace_id, **values):
        self.get(actor, organization_id, workspace_id)
        if values["expected_version"] != self.workspace.version:
            raise WorkspaceVersionConflict("Workspace version is stale")
        self.workspace = self.workspace.update_metadata(
            name=values.get("name"),
            slug=values.get("slug"),
            description=values.get("description"),
            description_provided="description" in values,
            at=NOW,
        )
        return self.workspace

    def update_configuration(
        self, actor, organization_id, workspace_id, patch, *, expected_version
    ):
        self.get(actor, organization_id, workspace_id)
        if expected_version != self.configuration.version:
            raise WorkspaceVersionConflict("Workspace configuration version is stale")
        from app.domain.tenancy import WorkspaceConfigurationPatch

        self.configuration = self.configuration.update(
            WorkspaceConfigurationPatch.from_mapping(patch), actor=ACTOR, at=NOW
        )
        return self.configuration

    def archive(self, actor, organization_id, workspace_id, *, expected_version):
        self.get(actor, organization_id, workspace_id)
        if expected_version != self.workspace.version:
            raise WorkspaceVersionConflict("Workspace version is stale")
        self.workspace = self.workspace.archive(at=NOW)
        return self.workspace


def _client(service: WorkspaceService | None = None) -> TestClient:
    application = FastAPI()
    application.include_router(
        build_hosted_workspace_router(
            service or WorkspaceService(), lambda: _actor(), cursor_codec=CURSORS
        )
    )
    return TestClient(application)


def test_hosted_workspace_lifecycle_contract() -> None:
    client = _client()
    prefix = f"/v3/organizations/{ORG}/workspaces"

    page = client.get(prefix, params={"limit": 25})
    assert page.status_code == 200
    assert page.json()["items"][0]["workspace_id"] == str(WORKSPACE)
    assert page.json()["next_cursor"] is None

    detail = client.get(f"{prefix}/{WORKSPACE}")
    assert detail.status_code == 200
    assert detail.json()["configuration"] == {
        "schema_version": 1,
        "version": 1,
        "rag_top_k": 8,
        "llm_temperature": 0.2,
        "updated_at": NOW.isoformat().replace("+00:00", "Z"),
    }

    created = client.post(
        prefix,
        json={"name": "Production", "slug": "production", "description": "Ops"},
    )
    assert created.status_code == 201

    updated = client.patch(
        f"{prefix}/{WORKSPACE}",
        json={"expected_version": 1, "name": "Production systems"},
    )
    assert updated.status_code == 200
    assert updated.json()["workspace"]["version"] == 2

    configured = client.patch(
        f"{prefix}/{WORKSPACE}/configuration",
        json={"expected_version": 1, "rag_top_k": 12},
    )
    assert configured.status_code == 200
    assert configured.json()["configuration"]["rag_top_k"] == 12

    archived = client.post(
        f"{prefix}/{WORKSPACE}/archive", json={"expected_version": 2}
    )
    assert archived.status_code == 200
    assert archived.json()["state"] == "archived"


def test_workspace_routes_fail_closed_and_keep_errors_distinct() -> None:
    client = _client()
    prefix = f"/v3/organizations/{ORG}/workspaces"
    denied = client.get(
        "/v3/organizations/00000000-0000-4000-8000-000000000099/workspaces"
    )
    assert denied.status_code == 403
    assert client.get(
        f"{prefix}/00000000-0000-4000-8000-000000000099"
    ).status_code == 404
    assert client.patch(
        f"{prefix}/{WORKSPACE}",
        json={"expected_version": 99, "name": "Stale"},
    ).status_code == 409
    assert client.patch(
        f"{prefix}/{WORKSPACE}/configuration",
        json={"expected_version": 1, "unknown": True},
    ).status_code == 422
    assert client.get(prefix, params={"cursor": "not-a-cursor"}).status_code == 422
    assert client.get(prefix, params={"cursor": "a" * 513}).status_code == 422


def test_workspace_routes_preserve_authentication_boundary() -> None:
    def deny():
        raise HTTPException(status_code=401, detail="Unauthorized")

    application = FastAPI()
    application.include_router(
        build_hosted_workspace_router(
            WorkspaceService(), deny, cursor_codec=CURSORS
        )
    )
    response = TestClient(application).get(f"/v3/organizations/{ORG}/workspaces")
    assert response.status_code == 401


def test_workspace_cursor_is_tamper_evident_and_organization_bound() -> None:
    class PaginatedWorkspaceService(WorkspaceService):
        def list_visible_page(self, actor, organization_id, *, limit, before=None):
            if before is not None:
                return WorkspacePage((), None)
            return WorkspacePage(
                (self.workspace,),
                WorkspaceListCursor(self.workspace.created_at, self.workspace.id),
            )

    client = _client(PaginatedWorkspaceService())
    prefix = f"/v3/organizations/{ORG}/workspaces"
    cursor = client.get(prefix, params={"limit": 1}).json()["next_cursor"]

    replacement = "A" if cursor[-1] != "A" else "B"
    assert client.get(
        prefix, params={"cursor": cursor[:-1] + replacement}
    ).status_code == 422
    foreign_org = "00000000-0000-4000-8000-000000000099"
    assert client.get(
        f"/v3/organizations/{foreign_org}/workspaces", params={"cursor": cursor}
    ).status_code == 422
