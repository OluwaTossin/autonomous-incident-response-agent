"""Hosted workspace lifecycle, configuration, and authorization tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.application.workspaces import (
    HostedWorkspaceService,
    WorkspaceConflict,
    WorkspaceVersionConflict,
)
from app.auth.context import ActorContext, AuthenticationMethod, trusted_system_actor
from app.authorization.permissions import Permission
from app.authorization.service import (
    AuthorizationDenied,
    AuthorizationService,
    HumanAuthorizationFacts,
    ServiceAccountAuthorizationFacts,
    SystemAuthorizationGrant,
)
from app.domain.common import ActorKind, ActorReference, DomainInvariantError
from app.domain.identifiers import (
    MembershipId,
    OrganizationId,
    ServiceAccountGrantId,
    ServiceAccountId,
    UserId,
    WorkspaceId,
)
from app.domain.tenancy import (
    MembershipRole,
    Workspace,
    WorkspaceAccessMode,
    WorkspaceConfiguration,
    WorkspaceConfigurationPatch,
    WorkspaceState,
)

NOW = datetime(2026, 9, 24, 14, 0, tzinfo=UTC)


def _id(identifier_type, suffix: int):
    return identifier_type(f"00000000-0000-4000-8000-{suffix:012d}")


ORG = _id(OrganizationId, 1)
OTHER_ORG = _id(OrganizationId, 2)
WORKSPACE = _id(WorkspaceId, 10)
OTHER_WORKSPACE = _id(WorkspaceId, 11)
OWNER_ID = _id(UserId, 20)
ADMIN_ID = _id(UserId, 24)
OPERATOR_ID = _id(UserId, 21)
VIEWER_ID = _id(UserId, 22)
SERVICE_ID = _id(ServiceAccountId, 23)


def _human(user_id: UserId) -> ActorContext:
    return ActorContext(
        actor=ActorReference(ActorKind.HUMAN, actor_id=user_id),
        authentication_method=AuthenticationMethod.OIDC,
        issuer="https://issuer.example",
        external_subject=f"subject-{user_id}",
    )


def _service_account() -> ActorContext:
    return ActorContext(
        actor=ActorReference(ActorKind.SERVICE_ACCOUNT, actor_id=SERVICE_ID),
        authentication_method=AuthenticationMethod.SERVICE_ACCOUNT,
        credential_id="lookup-id",
    )


def _workspace(workspace_id: WorkspaceId = WORKSPACE) -> Workspace:
    return Workspace(
        id=workspace_id,
        organization_id=ORG,
        name=f"Workspace {workspace_id}",
        slug=f"workspace-{str(workspace_id)[-4:]}",
        created_by=_human(OWNER_ID).actor,
        created_at=NOW,
        updated_at=NOW,
    )


class Store:
    def __init__(self) -> None:
        self.workspaces = {WORKSPACE: _workspace(), OTHER_WORKSPACE: _workspace(OTHER_WORKSPACE)}
        self.configurations = {
            workspace_id: WorkspaceConfiguration(
                scope=workspace.scope,
                schema_version=1,
                version=1,
                rag_top_k=8,
                llm_temperature=0.2,
                updated_by=_human(OWNER_ID).actor,
                created_at=NOW,
                updated_at=NOW,
            )
            for workspace_id, workspace in self.workspaces.items()
        }
        self.audits = []
        self.roles = {
            OWNER_ID: MembershipRole.OWNER,
            ADMIN_ID: MembershipRole.ADMIN,
            OPERATOR_ID: MembershipRole.OPERATOR,
            VIEWER_ID: MembershipRole.VIEWER,
        }
        self.restricted_users: set[UserId] = set()
        self.allowed_workspaces: dict[UserId, set[WorkspaceId]] = {}
        self.service_permissions = frozenset({Permission.ORGANIZATION_READ, Permission.WORKSPACE_READ})

    def uow(self, context):
        return Uow(self)


class Facts:
    def __init__(self, store: Store) -> None:
        self.store = store

    def human_facts(self, actor, organization_id, workspace_id):
        role = self.store.roles.get(actor.actor.actor_id)
        if role is None or organization_id != ORG:
            return None
        restricted = actor.actor.actor_id in self.store.restricted_users
        return HumanAuthorizationFacts(
            _id(MembershipId, 100 + list(MembershipRole).index(role)),
            role,
            WorkspaceAccessMode.RESTRICTED if restricted else WorkspaceAccessMode.ALL,
            workspace_id in self.store.allowed_workspaces.get(actor.actor.actor_id, set()),
        )

    def service_account_facts(self, actor, organization_id, workspace_id):
        if actor.actor.actor_id != SERVICE_ID or organization_id != ORG:
            return None
        return ServiceAccountAuthorizationFacts(
            _id(ServiceAccountGrantId, 200),
            self.store.service_permissions,
            WorkspaceAccessMode.ALL,
            True,
        )

    def invited_membership_id(self, actor, organization_id):
        return None

    def visible_organization_ids(self, actor):
        return (ORG,)


class Resources:
    def __init__(self, store: Store) -> None:
        self.store = store

    def is_active(self, organization_id, workspace_id):
        if organization_id != ORG:
            return False
        if workspace_id is None:
            return True
        workspace = self.store.workspaces.get(workspace_id)
        return workspace is not None and workspace.state is WorkspaceState.ACTIVE


class WorkspaceRepo:
    def __init__(self, store: Store) -> None:
        self.store = store

    def add(self, workspace):
        if any(
            item.organization_id == workspace.organization_id
            and item.slug == workspace.slug
            for item in self.store.workspaces.values()
        ):
            raise WorkspaceConflict("Workspace slug already exists")
        self.store.workspaces[workspace.id] = workspace

    def get(self, workspace_id):
        return self.store.workspaces.get(workspace_id)

    def list(self):
        return list(self.store.workspaces.values())

    def list_page(self, *, limit, before):
        values = sorted(
            self.store.workspaces.values(),
            key=lambda item: (item.created_at, str(item.id)),
            reverse=True,
        )
        if before is not None:
            values = [
                item
                for item in values
                if (item.created_at, str(item.id))
                < (before.created_at, str(before.workspace_id))
            ]
        return values[:limit]

    def save(self, workspace, *, expected_version):
        current = self.store.workspaces.get(workspace.id)
        if current is None or current.version != expected_version:
            raise WorkspaceVersionConflict("Workspace version is stale")
        self.store.workspaces[workspace.id] = workspace


class ConfigurationRepo:
    def __init__(self, store: Store) -> None:
        self.store = store

    def add(self, configuration):
        self.store.configurations[configuration.scope.workspace_id] = configuration

    def get(self, workspace_id):
        return self.store.configurations.get(workspace_id)

    def save(self, configuration, *, expected_version):
        current = self.store.configurations.get(configuration.scope.workspace_id)
        if current is None or current.version != expected_version:
            raise WorkspaceVersionConflict("Workspace configuration version is stale")
        self.store.configurations[configuration.scope.workspace_id] = configuration


class AuditRepo:
    def __init__(self, store: Store) -> None:
        self.store = store

    def add(self, event):
        self.store.audits.append(event)


class Uow:
    def __init__(self, store: Store) -> None:
        self.workspaces = WorkspaceRepo(store)
        self.workspace_configurations = ConfigurationRepo(store)
        self.audit_events = AuditRepo(store)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None


def _workspace_service(
    store: Store,
    *,
    system_grants: tuple[SystemAuthorizationGrant, ...] = (),
) -> HostedWorkspaceService:
    return HostedWorkspaceService(
        AuthorizationService(
            Facts(store), Resources(store), system_grants=system_grants
        ),
        store.uow,
        clock=lambda: NOW,
    )


def test_owner_can_create_get_update_archive_with_audit() -> None:
    store = Store()
    service = _workspace_service(store)
    created = service.create(
        _human(OWNER_ID), ORG, name="Production", slug="Production"
    )
    assert created.slug == "production"
    assert service.get(_human(OWNER_ID), ORG, created.id) == created
    updated = service.update_metadata(
        _human(OWNER_ID),
        ORG,
        created.id,
        expected_version=1,
        name="Production API",
    )
    assert updated.version == 2
    archived = service.archive(
        _human(OWNER_ID), ORG, created.id, expected_version=2
    )
    assert archived.state is WorkspaceState.ARCHIVED
    with pytest.raises(AuthorizationDenied):
        service.get(_human(OWNER_ID), ORG, created.id)
    assert [event.event_type for event in store.audits[-3:]] == [
        "workspace.created",
        "workspace.metadata_updated",
        "workspace.archived",
    ]


def test_visible_workspace_page_is_bounded_and_respects_restrictions() -> None:
    store = Store()
    store.restricted_users.add(VIEWER_ID)
    store.allowed_workspaces[VIEWER_ID] = {WORKSPACE}
    service = _workspace_service(store)

    page = service.list_visible_page(_human(VIEWER_ID), ORG, limit=1)

    assert len(page.items) <= 1
    assert all(item.id == WORKSPACE for item in page.items)
    assert page.items == (store.workspaces[WORKSPACE],)
    assert page.next_cursor is None


def test_workspace_description_can_be_cleared_explicitly() -> None:
    store = Store()
    current = store.workspaces[WORKSPACE]
    store.workspaces[WORKSPACE] = Workspace(
        id=current.id,
        organization_id=current.organization_id,
        name=current.name,
        slug=current.slug,
        description="Remove me",
        created_by=current.created_by,
        created_at=current.created_at,
        updated_at=current.updated_at,
    )
    service = _workspace_service(store)

    updated = service.update_metadata(
        _human(OWNER_ID), ORG, WORKSPACE, expected_version=1, description=None
    )

    assert updated.description is None


@pytest.mark.parametrize(
    ("rag_top_k", "llm_temperature"),
    [(True, 0.2), (8.5, 0.2), (8, True), (8, "0.2")],
)
def test_workspace_configuration_domain_rejects_invalid_numeric_types(
    rag_top_k, llm_temperature
) -> None:
    with pytest.raises(DomainInvariantError):
        WorkspaceConfiguration(
            scope=_workspace().scope,
            schema_version=1,
            version=1,
            rag_top_k=rag_top_k,
            llm_temperature=llm_temperature,
            updated_by=_human(OWNER_ID).actor,
            created_at=NOW,
            updated_at=NOW,
        )


def test_operator_and_viewer_cannot_manage_workspace() -> None:
    store = Store()
    service = _workspace_service(store)
    for user_id in (OPERATOR_ID, VIEWER_ID):
        assert service.get(_human(user_id), ORG, WORKSPACE).id == WORKSPACE
        with pytest.raises(AuthorizationDenied):
            service.create(_human(user_id), ORG, name="Denied", slug="denied")
        with pytest.raises(AuthorizationDenied):
            service.update_metadata(
                _human(user_id),
                ORG,
                WORKSPACE,
                expected_version=1,
                name="Denied",
            )


def test_admin_can_create_and_update_workspace() -> None:
    store = Store()
    service = _workspace_service(store)
    created = service.create(
        _human(ADMIN_ID), ORG, name="Admin Workspace", slug="admin-workspace"
    )
    updated = service.update_metadata(
        _human(ADMIN_ID),
        ORG,
        created.id,
        expected_version=1,
        name="Admin Updated",
    )
    assert updated.name == "Admin Updated"


def test_restricted_members_only_list_and_read_granted_workspaces() -> None:
    store = Store()
    store.restricted_users.add(OPERATOR_ID)
    store.allowed_workspaces[OPERATOR_ID] = {WORKSPACE}
    service = _workspace_service(store)
    assert [item.id for item in service.list_visible(_human(OPERATOR_ID), ORG)] == [
        WORKSPACE
    ]
    with pytest.raises(AuthorizationDenied):
        service.get(_human(OPERATOR_ID), ORG, OTHER_WORKSPACE)


def test_configuration_is_typed_versioned_and_attributed() -> None:
    store = Store()
    service = _workspace_service(store)
    current = service.get_configuration(_human(OWNER_ID), ORG, WORKSPACE)
    updated = service.update_configuration(
        _human(OWNER_ID),
        ORG,
        WORKSPACE,
        {"rag_top_k": 12, "llm_temperature": 0.4},
        expected_version=current.version,
    )
    assert updated.version == 2
    assert updated.schema_version == 1
    assert updated.updated_by == _human(OWNER_ID).actor
    assert store.audits[-1].event_type == "workspace.configuration_updated"


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"rag_top_k": 0},
        {"llm_temperature": 3.0},
        {"unknown": True},
        {"api_key": "secret"},
        {"provider_secret": "secret"},
    ],
)
def test_configuration_rejects_invalid_unknown_and_secret_like_fields(raw) -> None:
    with pytest.raises(DomainInvariantError):
        WorkspaceConfigurationPatch.from_mapping(raw)


def test_optimistic_concurrency_rejects_stale_metadata_and_config() -> None:
    store = Store()
    service = _workspace_service(store)
    service.update_metadata(
        _human(OWNER_ID), ORG, WORKSPACE, expected_version=1, name="First"
    )
    with pytest.raises(WorkspaceVersionConflict):
        service.update_metadata(
            _human(OWNER_ID), ORG, WORKSPACE, expected_version=1, name="Stale"
        )
    service.update_configuration(
        _human(OWNER_ID), ORG, WORKSPACE, {"rag_top_k": 9}, expected_version=1
    )
    with pytest.raises(WorkspaceVersionConflict):
        service.update_configuration(
            _human(OWNER_ID),
            ORG,
            WORKSPACE,
            {"rag_top_k": 10},
            expected_version=1,
        )


def test_duplicate_slug_and_wrong_organization_fail_closed() -> None:
    store = Store()
    service = _workspace_service(store)
    with pytest.raises(WorkspaceConflict, match="slug"):
        service.create(
            _human(OWNER_ID), ORG, name="Duplicate", slug=_workspace().slug
        )
    with pytest.raises(AuthorizationDenied):
        service.get(_human(OWNER_ID), OTHER_ORG, WORKSPACE)


def test_service_account_and_system_require_explicit_permissions() -> None:
    store = Store()
    service = _workspace_service(store)
    assert service.get(_service_account(), ORG, WORKSPACE).id == WORKSPACE
    with pytest.raises(AuthorizationDenied):
        service.update_metadata(
            _service_account(),
            ORG,
            WORKSPACE,
            expected_version=1,
            name="Denied",
        )

    system = trusted_system_actor(
        system_name="workspace-reader",
        workload_issuer="https://sts.example",
        workload_subject="role/workspace-reader",
    )
    with pytest.raises(AuthorizationDenied):
        service.get(system, ORG, WORKSPACE)
    explicit = _workspace_service(
        store,
        system_grants=(
            SystemAuthorizationGrant(
                "workspace-reader",
                "https://sts.example",
                "role/workspace-reader",
                ORG,
                frozenset({Permission.WORKSPACE_READ}),
                frozenset({WORKSPACE}),
            ),
        ),
    )
    assert explicit.get(system, ORG, WORKSPACE).id == WORKSPACE
