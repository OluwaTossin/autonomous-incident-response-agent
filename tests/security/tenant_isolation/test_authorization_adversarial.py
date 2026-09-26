"""Adversarial actor, role, organization, and workspace authorization matrix."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.auth.context import ActorContext, AuthenticationMethod
from app.authorization.permissions import (
    ROLE_PERMISSIONS,
    SERVICE_ACCOUNT_GRANTABLE_PERMISSIONS,
    Permission,
)
from app.authorization.service import (
    AuthorizationDenied,
    AuthorizationService,
    HumanAuthorizationFacts,
    ServiceAccountAuthorizationFacts,
    SystemAuthorizationGrant,
)
from app.domain.common import ActorKind, ActorReference
from app.domain.identifiers import MembershipId, ServiceAccountGrantId
from app.domain.tenancy import MembershipRole, WorkspaceAccessMode

from .fixtures import (
    A1,
    A2,
    B1,
    ORG_A,
    ORG_B,
    SCOPES,
    SERVICE_IDS,
    USER_IDS,
    human,
    service_account,
    worker,
)


def _membership_id(role: MembershipRole) -> MembershipId:
    return MembershipId(f"00000000-0000-4000-8000-0000000004{list(MembershipRole).index(role):02d}")


@dataclass
class Facts:
    revoked_users: set = None
    revoked_services: set = None

    def __post_init__(self) -> None:
        self.revoked_users = self.revoked_users or set()
        self.revoked_services = self.revoked_services or set()

    def human_facts(self, actor, organization_id, workspace_id):
        user_id = actor.actor.actor_id
        if user_id in self.revoked_users:
            return None
        role = next(
            (
                candidate_role
                for (candidate_org, candidate_role), candidate_user in USER_IDS.items()
                if candidate_org == organization_id and candidate_user == user_id
            ),
            None,
        )
        if role is None:
            return None
        restricted = role in {MembershipRole.OPERATOR, MembershipRole.VIEWER}
        allowed = workspace_id in ({A1} if organization_id == ORG_A else {B1})
        return HumanAuthorizationFacts(
            _membership_id(role),
            role,
            WorkspaceAccessMode.RESTRICTED if restricted else WorkspaceAccessMode.ALL,
            allowed,
        )

    def service_account_facts(self, actor, organization_id, workspace_id):
        name = next(
            (name for name, service_id in {
                "a1": service_account("a1").actor.actor_id,
                "a2": service_account("a2").actor.actor_id,
                "b1": service_account("b1").actor.actor_id,
            }.items() if service_id == actor.actor.actor_id),
            None,
        )
        if name is None or name in self.revoked_services:
            return None
        scope = SCOPES[name]
        if organization_id != scope.organization_id:
            return None
        return ServiceAccountAuthorizationFacts(
            ServiceAccountGrantId(f"00000000-0000-4000-8000-0000000005{list(SCOPES).index(name):02d}"),
            frozenset({Permission.INCIDENT_READ, Permission.JOB_CREATE}),
            WorkspaceAccessMode.RESTRICTED,
            workspace_id == scope.workspace_id,
        )

    def invited_membership_id(self, actor, organization_id):
        return None

    def visible_organization_ids(self, actor):
        return tuple(
            organization_id
            for (organization_id, _role), user_id in USER_IDS.items()
            if user_id == actor.actor.actor_id and user_id not in self.revoked_users
        )


class Resources:
    def is_active(self, organization_id, workspace_id):
        return organization_id in {ORG_A, ORG_B} and (
            workspace_id is None
            or (organization_id, workspace_id)
            in {(ORG_A, A1), (ORG_A, A2), (ORG_B, B1), (ORG_B, SCOPES["b2"].workspace_id)}
        )


def _service(facts: Facts | None = None) -> AuthorizationService:
    return AuthorizationService(facts or Facts(), Resources())


@pytest.mark.parametrize("role", list(MembershipRole))
@pytest.mark.parametrize("permission", list(Permission))
def test_human_role_permission_matrix_is_enforced(role, permission) -> None:
    actor = human(ORG_A, role)
    workspace_id = A1 if permission.value.split(".", 1)[0] not in {
        "organization",
        "membership",
        "service_account",
        "audit",
    } else None
    if permission is Permission.ORGANIZATION_CREATE:
        with pytest.raises(AuthorizationDenied):
            _service().authorize(actor, ORG_A, permission, workspace_id=workspace_id)
    elif permission in ROLE_PERMISSIONS[role]:
        _service().authorize(actor, ORG_A, permission, workspace_id=workspace_id)
    else:
        with pytest.raises(AuthorizationDenied):
            _service().authorize(actor, ORG_A, permission, workspace_id=workspace_id)


def test_cross_org_cross_workspace_and_stale_membership_fail_closed() -> None:
    facts = Facts()
    service = _service(facts)
    operator = human(ORG_A, MembershipRole.OPERATOR)

    service.authorize(operator, ORG_A, Permission.INCIDENT_READ, workspace_id=A1)
    for organization_id, workspace_id in ((ORG_A, A2), (ORG_B, B1)):
        with pytest.raises(AuthorizationDenied, match="Access denied"):
            service.authorize(
                operator,
                organization_id,
                Permission.INCIDENT_READ,
                workspace_id=workspace_id,
            )

    facts.revoked_users.add(operator.actor.actor_id)
    with pytest.raises(AuthorizationDenied):
        service.authorize(operator, ORG_A, Permission.INCIDENT_READ, workspace_id=A1)


def test_service_account_scope_and_human_only_capabilities_are_denied() -> None:
    facts = Facts()
    service = _service(facts)
    actor = service_account("a1")
    service.authorize(actor, ORG_A, Permission.INCIDENT_READ, workspace_id=A1)

    for organization_id, workspace_id in ((ORG_A, A2), (ORG_B, B1)):
        with pytest.raises(AuthorizationDenied):
            service.authorize(
                actor,
                organization_id,
                Permission.INCIDENT_READ,
                workspace_id=workspace_id,
            )
    for permission in (
        Permission.MEMBERSHIP_UPDATE,
        Permission.APPROVAL_DECIDE,
        Permission.EXECUTION_INTENT_PREPARE,
        Permission.USAGE_READ,
    ):
        assert permission not in SERVICE_ACCOUNT_GRANTABLE_PERMISSIONS
        with pytest.raises(AuthorizationDenied):
            service.authorize(actor, ORG_A, permission, workspace_id=A1)

    facts.revoked_services.add("a1")
    with pytest.raises(AuthorizationDenied):
        service.authorize(actor, ORG_A, Permission.INCIDENT_READ, workspace_id=A1)


def test_system_actor_has_only_exact_workload_and_scope_grant() -> None:
    actor = worker()
    service = AuthorizationService(
        Facts(),
        Resources(),
        system_grants=(
            SystemAuthorizationGrant(
                "aira-worker",
                "aws:iam",
                "role/aira-worker",
                ORG_A,
                frozenset({Permission.JOB_EXECUTE}),
                frozenset({A1}),
            ),
        ),
    )
    service.authorize(actor, ORG_A, Permission.JOB_EXECUTE, workspace_id=A1)
    with pytest.raises(AuthorizationDenied):
        service.authorize(actor, ORG_A, Permission.JOB_EXECUTE, workspace_id=A2)
    with pytest.raises(AuthorizationDenied):
        service.authorize(actor, ORG_B, Permission.JOB_EXECUTE, workspace_id=B1)
    with pytest.raises(AuthorizationDenied):
        service.authorize(actor, ORG_A, Permission.APPROVAL_DECIDE, workspace_id=A1)


@pytest.mark.parametrize(
    ("kind", "method"),
    (
        (ActorKind.SERVICE_ACCOUNT, AuthenticationMethod.OIDC),
        (ActorKind.SYSTEM, AuthenticationMethod.SERVICE_ACCOUNT),
        (ActorKind.HUMAN, AuthenticationMethod.WORKLOAD_IDENTITY),
    ),
)
def test_actor_type_serialization_confusion_is_rejected(kind, method) -> None:
    reference = (
        ActorReference(kind, system_name="worker")
        if kind is ActorKind.SYSTEM
        else ActorReference(
            kind,
            actor_id=(
                next(iter(SERVICE_IDS.values()))
                if kind is ActorKind.SERVICE_ACCOUNT
                else next(iter(USER_IDS.values()))
            ),
        )
    )
    with pytest.raises(Exception):
        ActorContext(
            reference,
            method,
            issuer="https://issuer.example",
            external_subject="subject",
            credential_id="credential",
        )
