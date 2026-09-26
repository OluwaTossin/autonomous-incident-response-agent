"""Hosted workspace lifecycle and typed configuration services."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, Self, cast

from app.auth.context import ActorContext
from app.authorization.permissions import Permission
from app.authorization.service import (
    AuthorizationDenied,
    AuthorizationService,
    AuthorizedTenantContext,
)
from app.domain.common import CorrelationContext, OrganizationScope, WorkspaceScope
from app.domain.events import AuditEvent
from app.domain.identifiers import (
    AuditEventId,
    CorrelationId,
    OrganizationId,
    WorkspaceId,
)
from app.domain.tenancy import (
    WORKSPACE_CONFIG_SCHEMA_VERSION,
    Workspace,
    WorkspaceConfiguration,
    WorkspaceConfigurationPatch,
    WorkspaceState,
)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")
_UNSET = object()


class WorkspaceConflict(Exception):
    """A workspace name/slug or lifecycle operation conflicts with durable state."""


class WorkspaceVersionConflict(WorkspaceConflict):
    """The caller attempted to update a stale workspace/configuration version."""


class WorkspaceNotFound(Exception):
    """The authorized workspace record does not exist."""


@dataclass(frozen=True, slots=True)
class WorkspaceListCursor:
    created_at: datetime
    workspace_id: WorkspaceId


@dataclass(frozen=True, slots=True)
class WorkspacePage:
    items: tuple[Workspace, ...]
    next_cursor: WorkspaceListCursor | None


class WorkspaceRepository(Protocol):
    def add(self, workspace: Workspace) -> None: ...
    def get(self, workspace_id: WorkspaceId) -> Workspace | None: ...
    def list(self) -> Sequence[Workspace]: ...
    def list_page(
        self, *, limit: int, before: WorkspaceListCursor | None
    ) -> Sequence[Workspace]: ...
    def save(self, workspace: Workspace, *, expected_version: int) -> None: ...


class WorkspaceConfigurationRepository(Protocol):
    def add(self, configuration: WorkspaceConfiguration) -> None: ...
    def get(self, workspace_id: WorkspaceId) -> WorkspaceConfiguration | None: ...
    def save(
        self,
        configuration: WorkspaceConfiguration,
        *,
        expected_version: int,
    ) -> None: ...


class AuditEventRepository(Protocol):
    def add(self, event: AuditEvent) -> None: ...


class WorkspaceUnitOfWork(Protocol):
    workspaces: WorkspaceRepository
    workspace_configurations: WorkspaceConfigurationRepository
    audit_events: AuditEventRepository

    def __enter__(self) -> Self: ...
    def __exit__(self, exc_type, exc_value, traceback) -> None: ...


WorkspaceUnitOfWorkFactory = Callable[
    [AuthorizedTenantContext], WorkspaceUnitOfWork
]


class HostedWorkspaceService:
    def __init__(
        self,
        authorization: AuthorizationService,
        uow_factory: WorkspaceUnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._authorization = authorization
        self._uow_factory = uow_factory
        self._clock = clock

    def create(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        *,
        name: str,
        slug: str,
        description: str | None = None,
        correlation: CorrelationContext | None = None,
    ) -> Workspace:
        now = self._clock()
        workspace = Workspace(
            id=WorkspaceId.new(),
            organization_id=organization_id,
            name=self._name(name),
            slug=self._slug(slug),
            description=self._description(description),
            created_by=actor.actor,
            created_at=now,
            updated_at=now,
        )
        context = self._authorization.authorize_workspace_creation(
            actor, organization_id, workspace.id
        )
        configuration = WorkspaceConfiguration(
            scope=workspace.scope,
            schema_version=WORKSPACE_CONFIG_SCHEMA_VERSION,
            version=1,
            rag_top_k=8,
            llm_temperature=0.2,
            updated_by=actor.actor,
            created_at=now,
            updated_at=now,
        )
        with self._uow_factory(context) as uow:
            uow.workspaces.add(workspace)
            uow.workspace_configurations.add(configuration)
            self._audit(
                uow,
                actor,
                workspace,
                "workspace.created",
                correlation,
                (("name", workspace.name), ("slug", workspace.slug)),
            )
        return workspace

    def get(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
    ) -> Workspace:
        context = self._authorization.authorize(
            actor,
            organization_id,
            Permission.WORKSPACE_READ,
            workspace_id=workspace_id,
        )
        with self._uow_factory(context) as uow:
            return self._required_workspace(uow, workspace_id)

    def list_visible(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
    ) -> tuple[Workspace, ...]:
        organization_context = self._authorization.authorize(
            actor, organization_id, Permission.ORGANIZATION_READ
        )
        with self._uow_factory(organization_context) as uow:
            candidates = tuple(uow.workspaces.list())
        visible: list[Workspace] = []
        for workspace in candidates:
            try:
                self._authorization.authorize(
                    actor,
                    organization_id,
                    Permission.WORKSPACE_READ,
                    workspace_id=workspace.id,
                )
            except AuthorizationDenied:
                continue
            visible.append(workspace)
        return tuple(visible)

    def list_visible_page(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        *,
        limit: int,
        before: WorkspaceListCursor | None = None,
    ) -> WorkspacePage:
        if not 1 <= limit <= 100:
            raise WorkspaceConflict("Workspace page limit must be between 1 and 100")
        organization_context = self._authorization.authorize(
            actor, organization_id, Permission.ORGANIZATION_READ
        )
        visible: list[Workspace] = []
        scan_before = before
        batch_size = 101
        while len(visible) <= limit:
            with self._uow_factory(organization_context) as uow:
                candidates = tuple(
                    uow.workspaces.list_page(limit=batch_size, before=scan_before)
                )
            if not candidates:
                break
            for workspace in candidates:
                try:
                    self._authorization.authorize(
                        actor,
                        organization_id,
                        Permission.WORKSPACE_READ,
                        workspace_id=workspace.id,
                    )
                except AuthorizationDenied:
                    continue
                visible.append(workspace)
                if len(visible) > limit:
                    break
            if len(visible) > limit or len(candidates) < batch_size:
                break
            last_candidate = candidates[-1]
            scan_before = WorkspaceListCursor(
                last_candidate.created_at, last_candidate.id
            )
        page = visible[:limit]
        next_cursor = (
            WorkspaceListCursor(page[-1].created_at, page[-1].id)
            if len(visible) > limit
            else None
        )
        return WorkspacePage(tuple(page), next_cursor)

    def update_metadata(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        *,
        expected_version: int,
        name: str | None = None,
        slug: str | None = None,
        description: str | None | object = _UNSET,
        correlation: CorrelationContext | None = None,
    ) -> Workspace:
        if name is None and slug is None and description is _UNSET:
            raise WorkspaceConflict("Workspace metadata update cannot be empty")
        context = self._authorization.authorize(
            actor,
            organization_id,
            Permission.WORKSPACE_UPDATE,
            workspace_id=workspace_id,
        )
        with self._uow_factory(context) as uow:
            current = self._required_workspace(uow, workspace_id)
            self._expected_version(current.version, expected_version)
            updated = current.update_metadata(
                name=self._name(name) if name is not None else None,
                slug=self._slug(slug) if slug is not None else None,
                description=(
                    self._description(cast(str | None, description))
                    if description is not _UNSET
                    else None
                ),
                description_provided=description is not _UNSET,
                at=self._clock(),
            )
            uow.workspaces.save(updated, expected_version=expected_version)
            self._audit(
                uow,
                actor,
                updated,
                "workspace.metadata_updated",
                correlation,
                (
                    ("before_name", current.name),
                    ("after_name", updated.name),
                    ("before_slug", current.slug),
                    ("after_slug", updated.slug),
                ),
            )
            return updated

    def archive(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        *,
        expected_version: int,
        correlation: CorrelationContext | None = None,
    ) -> Workspace:
        context = self._authorization.authorize(
            actor,
            organization_id,
            Permission.WORKSPACE_ARCHIVE,
            workspace_id=workspace_id,
        )
        with self._uow_factory(context) as uow:
            current = self._required_workspace(uow, workspace_id)
            self._expected_version(current.version, expected_version)
            archived = current.archive(at=self._clock())
            uow.workspaces.save(archived, expected_version=expected_version)
            self._audit(
                uow,
                actor,
                archived,
                "workspace.archived",
                correlation,
                (("previous_state", current.state.value),),
            )
            return archived

    def get_configuration(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
    ) -> WorkspaceConfiguration:
        context = self._authorization.authorize(
            actor,
            organization_id,
            Permission.WORKSPACE_READ,
            workspace_id=workspace_id,
        )
        with self._uow_factory(context) as uow:
            self._required_workspace(uow, workspace_id)
            configuration = uow.workspace_configurations.get(workspace_id)
            if configuration is None:
                raise WorkspaceNotFound("Workspace configuration not found")
            return configuration

    def update_configuration(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        raw_patch: Mapping[str, Any],
        *,
        expected_version: int,
        correlation: CorrelationContext | None = None,
    ) -> WorkspaceConfiguration:
        patch = WorkspaceConfigurationPatch.from_mapping(raw_patch)
        context = self._authorization.authorize(
            actor,
            organization_id,
            Permission.WORKSPACE_UPDATE,
            workspace_id=workspace_id,
        )
        with self._uow_factory(context) as uow:
            self._required_workspace(uow, workspace_id)
            current = uow.workspace_configurations.get(workspace_id)
            if current is None:
                raise WorkspaceNotFound("Workspace configuration not found")
            self._expected_version(current.version, expected_version)
            updated = current.update(patch, actor=actor.actor, at=self._clock())
            uow.workspace_configurations.save(
                updated, expected_version=expected_version
            )
            self._audit(
                uow,
                actor,
                self._required_workspace(uow, workspace_id),
                "workspace.configuration_updated",
                correlation,
                (
                    ("before_rag_top_k", str(current.rag_top_k)),
                    ("after_rag_top_k", str(updated.rag_top_k)),
                    (
                        "before_llm_temperature",
                        str(current.llm_temperature),
                    ),
                    ("after_llm_temperature", str(updated.llm_temperature)),
                    ("schema_version", str(updated.schema_version)),
                ),
            )
            return updated

    @staticmethod
    def _required_workspace(
        uow: WorkspaceUnitOfWork, workspace_id: WorkspaceId
    ) -> Workspace:
        workspace = uow.workspaces.get(workspace_id)
        if workspace is None:
            raise WorkspaceNotFound("Workspace not found")
        if workspace.state is WorkspaceState.ARCHIVED:
            raise WorkspaceConflict("Archived workspace is unavailable")
        return workspace

    @staticmethod
    def _expected_version(current: int, expected: int) -> None:
        if expected < 1 or current != expected:
            raise WorkspaceVersionConflict("Workspace version is stale")

    @staticmethod
    def _name(value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 200:
            raise WorkspaceConflict("Workspace name must be 1 to 200 characters")
        return normalized

    @staticmethod
    def _slug(value: str) -> str:
        normalized = value.strip().lower()
        if not _SLUG_RE.fullmatch(normalized):
            raise WorkspaceConflict(
                "Workspace slug must use 1 to 100 lowercase letters, digits, or hyphens"
            )
        return normalized

    @staticmethod
    def _description(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if len(normalized) > 1000:
            raise WorkspaceConflict("Workspace description cannot exceed 1000 characters")
        return normalized or None

    def _audit(
        self,
        uow: WorkspaceUnitOfWork,
        actor: ActorContext,
        workspace: Workspace,
        event_type: str,
        correlation: CorrelationContext | None,
        details: tuple[tuple[str, str], ...],
    ) -> None:
        uow.audit_events.add(
            AuditEvent(
                id=AuditEventId.new(),
                organization_scope=OrganizationScope(workspace.organization_id),
                workspace_scope=WorkspaceScope(
                    workspace.organization_id, workspace.id
                ),
                event_type=event_type,
                target_type="workspace",
                target_id=str(workspace.id),
                actor=actor.actor,
                occurred_at=self._clock(),
                correlation=correlation
                or CorrelationContext(CorrelationId.new()),
                details=details,
            )
        )
