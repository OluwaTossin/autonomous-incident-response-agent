"""Organization and membership lifecycle application tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.application.governance import GovernanceConflict, OrganizationGovernanceService
from app.auth.context import ActorContext, AuthenticationMethod
from app.authorization.service import (
    AuthorizationDenied,
    AuthorizationService,
    HumanAuthorizationFacts,
)
from app.domain.common import ActorKind, ActorReference
from app.domain.identifiers import MembershipId, OrganizationId, UserId, WorkspaceId
from app.domain.tenancy import (
    MembershipRole,
    MembershipState,
    OrganizationMembership,
    WorkspaceAccessMode,
)

NOW = datetime(2026, 9, 24, 10, 0, tzinfo=UTC)


def _id(identifier_type, suffix: int):
    return identifier_type(f"00000000-0000-4000-8000-{suffix:012d}")


OWNER_USER = _id(UserId, 1)
ADMIN_USER = _id(UserId, 2)
TARGET_USER = _id(UserId, 3)
ORG = _id(OrganizationId, 10)
WORKSPACE = _id(WorkspaceId, 20)


def _actor(user_id: UserId = OWNER_USER) -> ActorContext:
    return ActorContext(
        actor=ActorReference(ActorKind.HUMAN, actor_id=user_id),
        authentication_method=AuthenticationMethod.OIDC,
        issuer="https://issuer.example",
        external_subject=f"subject-{user_id}",
    )


def _membership(
    suffix: int,
    user_id: UserId,
    role: MembershipRole,
    state: MembershipState = MembershipState.ACTIVE,
) -> OrganizationMembership:
    return OrganizationMembership(
        id=_id(MembershipId, suffix),
        organization_id=ORG,
        user_id=user_id,
        role=role,
        state=state,
        created_by=_actor().actor,
        created_at=NOW,
        updated_at=NOW,
    )


class Facts:
    def __init__(self, store) -> None:
        self.store = store

    def human_facts(self, actor, organization_id, workspace_id):
        for membership in self.store.memberships.values():
            if (
                membership.organization_id == organization_id
                and membership.user_id == actor.actor.actor_id
                and membership.state is MembershipState.ACTIVE
            ):
                return HumanAuthorizationFacts(
                    membership.id,
                    membership.role,
                    membership.workspace_access,
                    True,
                )
        return None

    def service_account_facts(self, actor, organization_id, workspace_id):
        return None

    def invited_membership_id(self, actor, organization_id):
        for membership in self.store.memberships.values():
            if (
                membership.organization_id == organization_id
                and membership.user_id == actor.actor.actor_id
                and membership.state is MembershipState.INVITED
            ):
                return membership.id
        return None

    def visible_organization_ids(self, actor):
        return tuple(
            membership.organization_id
            for membership in self.store.memberships.values()
            if membership.user_id == actor.actor.actor_id
            and membership.state is MembershipState.ACTIVE
        )


class Resources:
    def is_active(self, organization_id, workspace_id):
        return organization_id == ORG and workspace_id in {None, WORKSPACE}


class Memberships:
    def __init__(self, store) -> None:
        self.store = store

    def add(self, membership):
        if any(
            existing.organization_id == membership.organization_id
            and existing.user_id == membership.user_id
            for existing in self.store.memberships.values()
        ):
            raise GovernanceConflict("Membership already exists")
        self.store.memberships[membership.id] = membership

    def save(self, membership):
        self.store.memberships[membership.id] = membership

    def get(self, membership_id):
        return self.store.memberships.get(membership_id)

    def get_for_user(self, organization_id, user_id):
        return next(
            (
                membership
                for membership in self.store.memberships.values()
                if membership.organization_id == organization_id
                and membership.user_id == user_id
            ),
            None,
        )

    def list(self):
        return list(self.store.memberships.values())

    def count_active_owners(self):
        return sum(
            membership.role is MembershipRole.OWNER
            and membership.state is MembershipState.ACTIVE
            for membership in self.store.memberships.values()
        )

    def lock_organization(self, organization_id):
        return None


class ReplacingGrants:
    def __init__(self) -> None:
        self.items = []

    def replace(self, owner_id, grants):
        self.items = list(grants)


class ServiceGrants:
    def __init__(self) -> None:
        self.items = {}

    def add(self, grant):
        self.items[grant.id] = grant

    def save(self, grant):
        self.items[grant.id] = grant

    def get(self, grant_id):
        return self.items.get(grant_id)

    def get_active(self, organization_id, service_account_id):
        return next(
            (
                grant
                for grant in self.items.values()
                if grant.organization_id == organization_id
                and grant.service_account_id == service_account_id
                and grant.active
            ),
            None,
        )


class Collecting:
    def __init__(self) -> None:
        self.items = []

    def add(self, item):
        self.items.append(item)


class Organizations(Collecting):
    def get(self, organization_id):
        return next(
            (
                organization
                for organization in self.items
                if organization.id == organization_id
            ),
            None,
        )


class Store:
    def __init__(self) -> None:
        self.memberships = {}
        self.organizations = Organizations()
        self.membership_workspace_grants = ReplacingGrants()
        self.service_account_grants = ServiceGrants()
        self.service_account_workspace_grants = ReplacingGrants()
        self.audit_events = Collecting()

    def uow(self, context):
        return Uow(self)


class Uow:
    def __init__(self, store) -> None:
        self.organizations = store.organizations
        self.memberships = Memberships(store)
        self.membership_workspace_grants = store.membership_workspace_grants
        self.service_account_grants = store.service_account_grants
        self.service_account_workspace_grants = store.service_account_workspace_grants
        self.audit_events = store.audit_events

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None


def _service(store: Store) -> OrganizationGovernanceService:
    return OrganizationGovernanceService(
        AuthorizationService(Facts(store), Resources()),
        store.uow,
        clock=lambda: NOW,
    )


def test_create_organization_creates_first_owner_and_audit() -> None:
    store = Store()
    organization = _service(store).create_organization(
        _actor(), name="AIRA", slug="aira"
    )
    owner = next(iter(store.memberships.values()))
    assert organization.id == owner.organization_id
    assert owner.role is MembershipRole.OWNER
    assert owner.state is MembershipState.ACTIVE
    assert store.audit_events.items[0].event_type == "organization.created"


def test_last_owner_cannot_be_demoted_suspended_or_removed() -> None:
    store = Store()
    owner = _membership(100, OWNER_USER, MembershipRole.OWNER)
    store.memberships[owner.id] = owner
    service = _service(store)

    with pytest.raises(GovernanceConflict, match="active Owner"):
        service.change_role(_actor(), ORG, owner.id, MembershipRole.ADMIN)
    with pytest.raises(GovernanceConflict, match="active Owner"):
        service.suspend_member(_actor(), ORG, owner.id)
    with pytest.raises(GovernanceConflict, match="active Owner"):
        service.remove_member(_actor(), ORG, owner.id)


def test_admin_cannot_manage_owner_or_promote_owner() -> None:
    store = Store()
    owner = _membership(100, OWNER_USER, MembershipRole.OWNER)
    admin = _membership(101, ADMIN_USER, MembershipRole.ADMIN)
    target = _membership(102, TARGET_USER, MembershipRole.VIEWER)
    store.memberships = {item.id: item for item in (owner, admin, target)}
    service = _service(store)

    with pytest.raises(AuthorizationDenied):
        service.suspend_member(_actor(ADMIN_USER), ORG, owner.id)
    with pytest.raises(AuthorizationDenied):
        service.change_role(
            _actor(ADMIN_USER), ORG, target.id, MembershipRole.OWNER
        )


def test_invitation_acceptance_removal_and_reinvite_are_audited() -> None:
    store = Store()
    owner = _membership(100, OWNER_USER, MembershipRole.OWNER)
    store.memberships[owner.id] = owner
    service = _service(store)
    invited = service.invite_member(
        _actor(), ORG, user_id=TARGET_USER, role=MembershipRole.OPERATOR
    )
    active = service.accept_invitation(_actor(TARGET_USER), ORG)
    removed = service.remove_member(_actor(), ORG, active.id)
    reinvited = service.invite_member(
        _actor(), ORG, user_id=TARGET_USER, role=MembershipRole.VIEWER
    )

    assert invited.id == active.id == removed.id == reinvited.id
    assert reinvited.state is MembershipState.INVITED
    assert [event.event_type for event in store.audit_events.items] == [
        "membership.invited",
        "membership.activated",
        "membership.removed",
        "membership.invited",
    ]


def test_workspace_restrictions_are_narrowing_and_audited() -> None:
    store = Store()
    owner = _membership(100, OWNER_USER, MembershipRole.OWNER)
    target = _membership(102, TARGET_USER, MembershipRole.OPERATOR)
    store.memberships = {owner.id: owner, target.id: target}
    updated = _service(store).set_workspace_restrictions(
        _actor(),
        ORG,
        target.id,
        WorkspaceAccessMode.RESTRICTED,
        [WORKSPACE],
    )
    assert updated.workspace_access is WorkspaceAccessMode.RESTRICTED
    assert len(store.membership_workspace_grants.items) == 1
    assert (
        store.audit_events.items[-1].event_type
        == "membership.workspace_restrictions_changed"
    )


def test_duplicate_active_membership_is_rejected() -> None:
    store = Store()
    owner = _membership(100, OWNER_USER, MembershipRole.OWNER)
    target = _membership(102, TARGET_USER, MembershipRole.VIEWER)
    store.memberships = {owner.id: owner, target.id: target}
    with pytest.raises(GovernanceConflict, match="already exists"):
        _service(store).invite_member(
            _actor(), ORG, user_id=TARGET_USER, role=MembershipRole.OPERATOR
        )
