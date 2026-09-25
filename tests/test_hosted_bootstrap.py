"""Hosted browser bootstrap contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.hosted_bootstrap import build_hosted_bootstrap_router
from app.application.bootstrap import HostedBootstrapService
from app.application.workspaces import WorkspacePage
from app.auth.context import ActorContext, AuthenticationMethod
from app.authorization.service import HumanAuthorizationFacts
from app.domain.common import ActorKind, ActorReference
from app.domain.identifiers import (
    MembershipId,
    OrganizationId,
    UserId,
    WorkspaceId,
)
from app.domain.tenancy import (
    MembershipRole,
    Organization,
    Workspace,
    WorkspaceAccessMode,
)

NOW = datetime(2026, 9, 25, tzinfo=UTC)
USER_ID = UserId("00000000-0000-4000-8000-000000000001")
ORG_ID = OrganizationId("00000000-0000-4000-8000-000000000002")
WORKSPACE_ID = WorkspaceId("00000000-0000-4000-8000-000000000003")


def _actor() -> ActorContext:
    return ActorContext(
        ActorReference(ActorKind.HUMAN, actor_id=USER_ID),
        AuthenticationMethod.OIDC,
        issuer="https://issuer.example",
        external_subject="subject",
    )


class Authorization:
    def human_membership_facts(self, actor, organization_id):
        return HumanAuthorizationFacts(
            MembershipId("00000000-0000-4000-8000-000000000004"),
            MembershipRole.OPERATOR,
            WorkspaceAccessMode.ALL,
            True,
        )


class Governance:
    def list_organizations(self, actor):
        return (
            Organization(
                ORG_ID,
                "Example Operations",
                "example-operations",
                actor.actor,
                NOW,
                NOW,
            ),
        )


class Workspaces:
    def list_visible_page(self, actor, organization_id, *, limit, before=None):
        assert limit == 100
        return WorkspacePage(
            (
                Workspace(
                WORKSPACE_ID,
                ORG_ID,
                "Production",
                "production",
                actor.actor,
                NOW,
                NOW,
                ),
            ),
            None,
        )


def test_bootstrap_returns_only_authoritative_scope_and_permissions() -> None:
    service = HostedBootstrapService(Authorization(), Governance(), Workspaces())
    bootstrap = service.get(_actor())

    assert bootstrap.user_id == str(USER_ID)
    assert bootstrap.organizations[0].role == "operator"
    assert bootstrap.organizations[0].membership_state == "active"
    assert "incident.create" in bootstrap.organizations[0].permissions
    assert bootstrap.organizations[0].workspaces[0].id == str(WORKSPACE_ID)


def test_me_route_uses_authenticated_actor_dependency() -> None:
    service = HostedBootstrapService(Authorization(), Governance(), Workspaces())
    app = FastAPI()
    app.include_router(build_hosted_bootstrap_router(service, _actor))

    response = TestClient(app).get("/v3/me")

    assert response.status_code == 200
    assert response.json()["organizations"][0]["organization_id"] == str(ORG_ID)
    assert response.json()["organizations"][0]["membership_state"] == "active"
    assert response.json()["organizations"][0]["workspaces"][0] == {
        "workspace_id": str(WORKSPACE_ID),
        "name": "Production",
        "slug": "production",
    }


def test_restricted_membership_does_not_advertise_workspace_creation() -> None:
    class RestrictedAuthorization:
        def human_membership_facts(self, actor, organization_id):
            return HumanAuthorizationFacts(
                MembershipId("00000000-0000-4000-8000-000000000004"),
                MembershipRole.ADMIN,
                WorkspaceAccessMode.RESTRICTED,
                False,
            )

    service = HostedBootstrapService(
        RestrictedAuthorization(), Governance(), Workspaces()
    )

    permissions = service.get(_actor()).organizations[0].permissions

    assert "workspace.create" not in permissions
    assert "workspace.update" in permissions
