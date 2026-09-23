"""Persistence ports required by the hosted foundation."""

from __future__ import annotations

from typing import Protocol

from app.domain.events import AuditEvent
from app.domain.identifiers import AuditEventId, IncidentId, OrganizationId, WorkspaceId
from app.domain.incidents import Incident
from app.domain.tenancy import Organization, Workspace


class OrganizationRepository(Protocol):
    def add(self, organization: Organization) -> None: ...

    def get(self, organization_id: OrganizationId) -> Organization | None: ...


class WorkspaceRepository(Protocol):
    def add(self, workspace: Workspace) -> None: ...

    def get(self, workspace_id: WorkspaceId) -> Workspace | None: ...


class IncidentRepository(Protocol):
    def add(self, incident: Incident) -> None: ...

    def get(self, incident_id: IncidentId) -> Incident | None: ...


class AuditEventRepository(Protocol):
    def add(self, event: AuditEvent) -> None: ...

    def get(self, event_id: AuditEventId) -> AuditEvent | None: ...
