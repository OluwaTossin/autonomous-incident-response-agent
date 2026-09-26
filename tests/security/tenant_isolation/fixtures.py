"""Deterministic two-organization adversarial identities and scopes."""

from __future__ import annotations

from app.auth.context import ActorContext, AuthenticationMethod, trusted_system_actor
from app.domain.common import ActorKind, ActorReference, WorkspaceScope
from app.domain.identifiers import OrganizationId, ServiceAccountId, UserId, WorkspaceId
from app.domain.tenancy import MembershipRole


def _id(identifier_type, suffix: int):
    return identifier_type(f"00000000-0000-4000-8000-{suffix:012d}")


ORG_A = _id(OrganizationId, 1)
ORG_B = _id(OrganizationId, 2)
A1 = _id(WorkspaceId, 11)
A2 = _id(WorkspaceId, 12)
B1 = _id(WorkspaceId, 21)
B2 = _id(WorkspaceId, 22)

SCOPES = {
    "a1": WorkspaceScope(ORG_A, A1),
    "a2": WorkspaceScope(ORG_A, A2),
    "b1": WorkspaceScope(ORG_B, B1),
    "b2": WorkspaceScope(ORG_B, B2),
}

USER_IDS = {
    (ORG_A, MembershipRole.OWNER): _id(UserId, 101),
    (ORG_A, MembershipRole.ADMIN): _id(UserId, 102),
    (ORG_A, MembershipRole.OPERATOR): _id(UserId, 103),
    (ORG_A, MembershipRole.VIEWER): _id(UserId, 104),
    (ORG_B, MembershipRole.OWNER): _id(UserId, 201),
    (ORG_B, MembershipRole.ADMIN): _id(UserId, 202),
    (ORG_B, MembershipRole.OPERATOR): _id(UserId, 203),
    (ORG_B, MembershipRole.VIEWER): _id(UserId, 204),
}

SERVICE_IDS = {
    "a1": _id(ServiceAccountId, 301),
    "a2": _id(ServiceAccountId, 302),
    "b1": _id(ServiceAccountId, 303),
}


def human(organization_id: OrganizationId, role: MembershipRole) -> ActorContext:
    user_id = USER_IDS[(organization_id, role)]
    return ActorContext(
        ActorReference(ActorKind.HUMAN, actor_id=user_id),
        AuthenticationMethod.OIDC,
        issuer="https://issuer.example",
        external_subject=f"subject-{user_id}",
    )


def service_account(name: str) -> ActorContext:
    service_id = SERVICE_IDS[name]
    return ActorContext(
        ActorReference(ActorKind.SERVICE_ACCOUNT, actor_id=service_id),
        AuthenticationMethod.SERVICE_ACCOUNT,
        credential_id=f"credential-{name}",
    )


def worker() -> ActorContext:
    return trusted_system_actor(
        system_name="aira-worker",
        workload_issuer="aws:iam",
        workload_subject="role/aira-worker",
    )
