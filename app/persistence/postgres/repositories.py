"""Tenant-scoped PostgreSQL repository implementations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.domain.events import AuditEvent
from app.domain.identifiers import AuditEventId, IncidentId, OrganizationId, WorkspaceId
from app.domain.incidents import Incident
from app.domain.tenancy import Organization, Workspace
from app.persistence.postgres.mappers import (
    audit_event_from_record,
    audit_event_to_record,
    incident_from_record,
    incident_to_record,
    organization_from_record,
    organization_to_record,
    workspace_from_record,
    workspace_to_record,
)
from app.persistence.postgres.models import (
    AuditEventRecord,
    IncidentRecord,
    OrganizationRecord,
    WorkspaceRecord,
)


class PostgresOrganizationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, organization: Organization) -> None:
        self._session.add(organization_to_record(organization))
        self._session.flush()

    def get(self, organization_id: OrganizationId) -> Organization | None:
        record = self._session.get(OrganizationRecord, UUID(str(organization_id)))
        return organization_from_record(record) if record else None


class PostgresWorkspaceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, workspace: Workspace) -> None:
        self._session.add(workspace_to_record(workspace))
        self._session.flush()

    def get(self, workspace_id: WorkspaceId) -> Workspace | None:
        record = self._session.get(WorkspaceRecord, UUID(str(workspace_id)))
        return workspace_from_record(record) if record else None


class PostgresIncidentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, incident: Incident) -> None:
        self._session.add(incident_to_record(incident))
        self._session.flush()

    def get(self, incident_id: IncidentId) -> Incident | None:
        record = self._session.get(IncidentRecord, UUID(str(incident_id)))
        return incident_from_record(record) if record else None


class PostgresAuditEventRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, event: AuditEvent) -> None:
        self._session.add(audit_event_to_record(event))
        self._session.flush()

    def get(self, event_id: AuditEventId) -> AuditEvent | None:
        record = self._session.get(AuditEventRecord, UUID(str(event_id)))
        return audit_event_from_record(record) if record else None
