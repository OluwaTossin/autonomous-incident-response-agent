"""Central permission policy and authorized-context tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.auth.context import ActorContext, AuthenticationMethod, trusted_system_actor
from app.authorization.permissions import ROLE_PERMISSIONS, Permission, role_allows
from app.authorization.service import (
    AuthorizationDenied,
    AuthorizationService,
    AuthorizedTenantContext,
    HumanAuthorizationFacts,
    ServiceAccountAuthorizationFacts,
    SystemAuthorizationGrant,
)
from app.domain.common import ActorKind, ActorReference
from app.domain.identifiers import (
    MembershipId,
    OrganizationId,
    ServiceAccountGrantId,
    ServiceAccountId,
    UserId,
    WorkspaceId,
)
from app.domain.tenancy import MembershipRole, WorkspaceAccessMode


def _id(identifier_type, suffix: int):
    return identifier_type(f"00000000-0000-4000-8000-{suffix:012d}")


ORG = _id(OrganizationId, 1)
OTHER_ORG = _id(OrganizationId, 2)
WORKSPACE = _id(WorkspaceId, 3)
OTHER_WORKSPACE = _id(WorkspaceId, 4)


def _human() -> ActorContext:
    return ActorContext(
        actor=ActorReference(ActorKind.HUMAN, actor_id=_id(UserId, 10)),
        authentication_method=AuthenticationMethod.OIDC,
        issuer="https://issuer.example",
        external_subject="person-10",
    )


def _service_account() -> ActorContext:
    return ActorContext(
        actor=ActorReference(
            ActorKind.SERVICE_ACCOUNT, actor_id=_id(ServiceAccountId, 20)
        ),
        authentication_method=AuthenticationMethod.SERVICE_ACCOUNT,
        credential_id="lookup-id",
    )


class Facts:
    role = MembershipRole.VIEWER
    state_version = 0
    active = True
    workspace_access = WorkspaceAccessMode.ALL
    workspace_allowed = True
    service_permissions = frozenset({Permission.INCIDENT_READ})

    def human_facts(self, actor, organization_id, workspace_id):
        if not self.active or organization_id != ORG:
            return None
        return HumanAuthorizationFacts(
            _id(MembershipId, 30),
            self.role,
            self.workspace_access,
            self.workspace_allowed,
        )

    def service_account_facts(self, actor, organization_id, workspace_id):
        if not self.active or organization_id != ORG:
            return None
        return ServiceAccountAuthorizationFacts(
            _id(ServiceAccountGrantId, 31),
            self.service_permissions,
            self.workspace_access,
            self.workspace_allowed,
        )

    def invited_membership_id(self, actor, organization_id):
        return _id(MembershipId, 30) if self.active and organization_id == ORG else None

    def visible_organization_ids(self, actor):
        return (ORG,) if self.active else ()


class Resources:
    active = True

    def is_active(self, organization_id, workspace_id):
        return self.active and organization_id == ORG and workspace_id != OTHER_WORKSPACE


@pytest.mark.parametrize("role", list(MembershipRole))
@pytest.mark.parametrize("permission", list(Permission))
def test_role_matrix_is_the_single_permission_source(role, permission) -> None:
    assert role_allows(role, permission) is (permission in ROLE_PERMISSIONS[role])


def test_role_semantics_match_approved_matrix() -> None:
    assert Permission.ORGANIZATION_UPDATE in ROLE_PERMISSIONS[MembershipRole.OWNER]
    assert Permission.ORGANIZATION_TRANSFER_OWNERSHIP in ROLE_PERMISSIONS[MembershipRole.OWNER]
    assert Permission.ORGANIZATION_TRANSFER_OWNERSHIP not in ROLE_PERMISSIONS[MembershipRole.ADMIN]
    assert Permission.MEMBERSHIP_INVITE in ROLE_PERMISSIONS[MembershipRole.ADMIN]
    assert Permission.TRIAGE_RUN in ROLE_PERMISSIONS[MembershipRole.OPERATOR]
    assert Permission.MEMBERSHIP_INVITE not in ROLE_PERMISSIONS[MembershipRole.OPERATOR]
    assert Permission.INCIDENT_READ in ROLE_PERMISSIONS[MembershipRole.VIEWER]
    assert Permission.INCIDENT_CREATE not in ROLE_PERMISSIONS[MembershipRole.VIEWER]


def test_approved_role_permission_sets_are_exact() -> None:
    viewer = {
        Permission.ORGANIZATION_READ,
        Permission.WORKSPACE_READ,
        Permission.INCIDENT_READ,
        Permission.KNOWLEDGE_READ,
        Permission.INTEGRATION_READ,
        Permission.ACTION_READ,
        Permission.APPROVAL_READ,
    }
    operator = viewer | {
        Permission.INCIDENT_CREATE,
        Permission.TRIAGE_RUN,
        Permission.KNOWLEDGE_MANAGE,
        Permission.ACTION_PROPOSE,
        Permission.AUDIT_READ,
    }
    admin = set(Permission) - {
        Permission.ORGANIZATION_CREATE,
        Permission.ORGANIZATION_TRANSFER_OWNERSHIP,
    }
    owner = set(Permission) - {Permission.ORGANIZATION_CREATE}
    assert ROLE_PERMISSIONS == {
        MembershipRole.OWNER: owner,
        MembershipRole.ADMIN: admin,
        MembershipRole.OPERATOR: operator,
        MembershipRole.VIEWER: viewer,
    }


def test_human_authorization_uses_fresh_durable_facts() -> None:
    facts = Facts()
    resources = Resources()
    service = AuthorizationService(facts, resources)
    facts.role = MembershipRole.OPERATOR

    context = service.authorize(
        _human(), ORG, Permission.TRIAGE_RUN, workspace_id=WORKSPACE
    )
    assert context.organization_id == ORG
    assert context.workspace_id == WORKSPACE

    facts.role = MembershipRole.VIEWER
    with pytest.raises(AuthorizationDenied, match="Access denied"):
        service.authorize(
            _human(), ORG, Permission.TRIAGE_RUN, workspace_id=WORKSPACE
        )


def test_suspended_or_wrong_tenant_fails_closed_without_context() -> None:
    facts = Facts()
    service = AuthorizationService(facts, Resources())
    facts.active = False
    with pytest.raises(AuthorizationDenied):
        service.authorize(_human(), ORG, Permission.ORGANIZATION_READ)
    facts.active = True
    with pytest.raises(AuthorizationDenied):
        service.authorize(_human(), OTHER_ORG, Permission.ORGANIZATION_READ)


def test_workspace_restrictions_narrow_but_never_create_access() -> None:
    facts = Facts()
    facts.role = MembershipRole.OPERATOR
    facts.workspace_access = WorkspaceAccessMode.RESTRICTED
    service = AuthorizationService(facts, Resources())

    facts.workspace_allowed = True
    service.authorize(_human(), ORG, Permission.TRIAGE_RUN, workspace_id=WORKSPACE)
    facts.workspace_allowed = False
    with pytest.raises(AuthorizationDenied):
        service.authorize(_human(), ORG, Permission.TRIAGE_RUN, workspace_id=WORKSPACE)
    with pytest.raises(AuthorizationDenied):
        service.authorize(
            _human(), ORG, Permission.TRIAGE_RUN, workspace_id=OTHER_WORKSPACE
        )


def test_restricted_members_cannot_create_workspaces() -> None:
    facts = Facts()
    facts.role = MembershipRole.ADMIN
    facts.workspace_access = WorkspaceAccessMode.RESTRICTED
    service = AuthorizationService(facts, Resources())
    with pytest.raises(AuthorizationDenied):
        service.authorize(_human(), ORG, Permission.WORKSPACE_CREATE)


def test_service_account_requires_explicit_revocable_grant() -> None:
    facts = Facts()
    service = AuthorizationService(facts, Resources())
    service.authorize(
        _service_account(), ORG, Permission.INCIDENT_READ, workspace_id=WORKSPACE
    )
    with pytest.raises(AuthorizationDenied):
        service.authorize(
            _service_account(), ORG, Permission.TRIAGE_RUN, workspace_id=WORKSPACE
        )
    facts.active = False
    with pytest.raises(AuthorizationDenied):
        service.authorize(
            _service_account(), ORG, Permission.INCIDENT_READ, workspace_id=WORKSPACE
        )


def test_system_actor_has_no_implicit_bypass() -> None:
    actor = trusted_system_actor(
        system_name="worker",
        workload_issuer="https://sts.example",
        workload_subject="role/worker",
    )
    facts = Facts()
    with pytest.raises(AuthorizationDenied):
        AuthorizationService(facts, Resources()).authorize(
            actor, ORG, Permission.INCIDENT_READ, workspace_id=WORKSPACE
        )

    configured = AuthorizationService(
        facts,
        Resources(),
        system_grants=(
            SystemAuthorizationGrant(
                "worker",
                "https://sts.example",
                "role/worker",
                ORG,
                frozenset({Permission.INCIDENT_READ}),
                frozenset({WORKSPACE}),
            ),
        ),
    )
    configured.authorize(
        actor, ORG, Permission.INCIDENT_READ, workspace_id=WORKSPACE
    )


def test_context_is_sealed_and_archived_resources_are_denied() -> None:
    actor = _human()
    with pytest.raises(TypeError):
        AuthorizedTenantContext(
            actor=actor.actor,
            organization_id=ORG,
            workspace_id=None,
            permission=Permission.ORGANIZATION_READ,
            authorization_source_id="request-body",
            _seal=object(),
        )
    resources = Resources()
    resources.active = False
    with pytest.raises(AuthorizationDenied):
        AuthorizationService(Facts(), resources).authorize(
            actor, ORG, Permission.ORGANIZATION_READ
        )


def test_actor_context_cannot_carry_jwt_roles_or_tenants() -> None:
    actor = _human()
    assert not hasattr(actor, "role")
    assert not hasattr(actor, "organization_id")
    assert not hasattr(actor, "workspace_id")
    assert replace(actor, request_id="request-1").request_id == "request-1"
