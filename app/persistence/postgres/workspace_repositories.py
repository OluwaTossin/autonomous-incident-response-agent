"""PostgreSQL repositories for hosted workspace state and configuration."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.workspaces import (
    WorkspaceConflict,
    WorkspaceListCursor,
    WorkspaceVersionConflict,
)
from app.domain.identifiers import WorkspaceId
from app.domain.tenancy import Workspace, WorkspaceConfiguration
from app.persistence.postgres.mappers import (
    workspace_configuration_from_record,
    workspace_configuration_to_record,
    workspace_from_record,
    workspace_to_record,
)
from app.persistence.postgres.models import (
    WorkspaceConfigurationRecord,
    WorkspaceRecord,
)


class PostgresHostedWorkspaceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, workspace: Workspace) -> None:
        try:
            self._session.add(workspace_to_record(workspace))
            self._session.flush()
        except IntegrityError as exc:
            raise WorkspaceConflict("Workspace slug already exists") from exc

    def get(self, workspace_id: WorkspaceId) -> Workspace | None:
        record = self._session.get(WorkspaceRecord, UUID(str(workspace_id)))
        return workspace_from_record(record) if record else None

    def list(self) -> list[Workspace]:
        records = self._session.scalars(
            select(WorkspaceRecord).order_by(
                WorkspaceRecord.created_at, WorkspaceRecord.id
            )
        ).all()
        return [workspace_from_record(record) for record in records]

    def list_page(
        self,
        *,
        limit: int,
        before: WorkspaceListCursor | None,
    ) -> list[Workspace]:
        statement = select(WorkspaceRecord)
        if before is not None:
            statement = statement.where(
                (WorkspaceRecord.created_at < before.created_at)
                | (
                    (WorkspaceRecord.created_at == before.created_at)
                    & (WorkspaceRecord.id < UUID(str(before.workspace_id)))
                )
            )
        records = self._session.scalars(
            statement.order_by(
                WorkspaceRecord.created_at.desc(), WorkspaceRecord.id.desc()
            ).limit(limit)
        ).all()
        return [workspace_from_record(record) for record in records]

    def save(self, workspace: Workspace, *, expected_version: int) -> None:
        try:
            result = self._session.execute(
                update(WorkspaceRecord)
                .where(
                    WorkspaceRecord.id == UUID(str(workspace.id)),
                    WorkspaceRecord.organization_id
                    == UUID(str(workspace.organization_id)),
                    WorkspaceRecord.version == expected_version,
                )
                .values(
                    name=workspace.name,
                    slug=workspace.slug,
                    description=workspace.description,
                    state=workspace.state.value,
                    version=workspace.version,
                    updated_at=workspace.updated_at,
                )
            )
            if result.rowcount != 1:
                raise WorkspaceVersionConflict("Workspace version is stale")
            self._session.flush()
        except IntegrityError as exc:
            raise WorkspaceConflict("Workspace slug already exists") from exc


class PostgresWorkspaceConfigurationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, configuration: WorkspaceConfiguration) -> None:
        self._session.add(workspace_configuration_to_record(configuration))
        self._session.flush()

    def get(self, workspace_id: WorkspaceId) -> WorkspaceConfiguration | None:
        record = self._session.get(
            WorkspaceConfigurationRecord, UUID(str(workspace_id))
        )
        return workspace_configuration_from_record(record) if record else None

    def save(
        self,
        configuration: WorkspaceConfiguration,
        *,
        expected_version: int,
    ) -> None:
        actor = configuration.updated_by
        result = self._session.execute(
            update(WorkspaceConfigurationRecord)
            .where(
                WorkspaceConfigurationRecord.workspace_id
                == UUID(str(configuration.scope.workspace_id)),
                WorkspaceConfigurationRecord.organization_id
                == UUID(str(configuration.scope.organization_id)),
                WorkspaceConfigurationRecord.version == expected_version,
            )
            .values(
                schema_version=configuration.schema_version,
                version=configuration.version,
                rag_top_k=configuration.rag_top_k,
                llm_temperature=configuration.llm_temperature,
                updated_by_kind=actor.kind.value,
                updated_by_id=(
                    UUID(str(actor.actor_id)) if actor.actor_id is not None else None
                ),
                updated_by_system_name=actor.system_name,
                updated_at=configuration.updated_at,
            )
        )
        if result.rowcount != 1:
            raise WorkspaceVersionConflict("Workspace configuration version is stale")
        self._session.flush()
