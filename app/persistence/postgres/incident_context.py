"""PostgreSQL repository for immutable incident context snapshots."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.common import WorkspaceScope
from app.domain.identifiers import (
    IncidentContextItemId,
    IncidentContextSnapshotId,
    IncidentId,
    IntegrationId,
    OrganizationId,
    TriageRunId,
    WorkspaceId,
)
from app.domain.incident_context import (
    CollectorDiagnostic,
    CollectorStatus,
    ContextCollectionStatus,
    ContextItemType,
    IncidentContextItem,
    IncidentContextSnapshot,
)
from app.persistence.postgres.models import (
    IncidentContextItemRecord,
    IncidentContextSnapshotRecord,
)


class PostgresIncidentContextRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_run(
        self, run_id: TriageRunId, *, for_update: bool = False
    ) -> IncidentContextSnapshot | None:
        statement = select(IncidentContextSnapshotRecord).where(
            IncidentContextSnapshotRecord.triage_run_id == UUID(str(run_id))
        )
        if for_update:
            statement = statement.with_for_update()
        record = self._session.scalar(statement)
        if record is None:
            return None
        items = self._session.scalars(
            select(IncidentContextItemRecord)
            .where(IncidentContextItemRecord.snapshot_id == record.id)
            .order_by(IncidentContextItemRecord.sequence)
        ).all()
        return _from_records(record, items)

    def add(self, snapshot: IncidentContextSnapshot) -> None:
        self._session.add(_to_record(snapshot))
        self._session.flush()
        self._session.add_all(_item_to_record(item) for item in snapshot.items)
        self._session.flush()


def _to_record(snapshot: IncidentContextSnapshot) -> IncidentContextSnapshotRecord:
    return IncidentContextSnapshotRecord(
        id=UUID(str(snapshot.id)),
        organization_id=UUID(str(snapshot.scope.organization_id)),
        workspace_id=UUID(str(snapshot.scope.workspace_id)),
        incident_id=UUID(str(snapshot.incident_id)),
        triage_run_id=UUID(str(snapshot.triage_run_id)),
        integration_id=UUID(str(snapshot.integration_id)),
        provider=snapshot.provider,
        region=snapshot.region,
        window_start=snapshot.window_start,
        window_end=snapshot.window_end,
        collected_at=snapshot.collected_at,
        status=snapshot.status.value,
        policy_version=snapshot.policy_version,
        diagnostics=[
            {
                "collector": diagnostic.collector,
                "status": diagnostic.status.value,
                "code": diagnostic.code,
                "summary": diagnostic.summary,
            }
            for diagnostic in snapshot.diagnostics
        ],
        truncated=snapshot.truncated,
    )


def _item_to_record(item: IncidentContextItem) -> IncidentContextItemRecord:
    return IncidentContextItemRecord(
        id=UUID(str(item.id)),
        organization_id=UUID(str(item.scope.organization_id)),
        workspace_id=UUID(str(item.scope.workspace_id)),
        snapshot_id=UUID(str(item.snapshot_id)),
        type=item.type.value,
        source=item.source,
        observed_at=item.observed_at,
        content=item.content,
        sequence=item.sequence,
        truncated=item.truncated,
    )


def _from_records(record, items) -> IncidentContextSnapshot:
    scope = WorkspaceScope(
        OrganizationId(str(record.organization_id)),
        WorkspaceId(str(record.workspace_id)),
    )
    snapshot_id = IncidentContextSnapshotId(str(record.id))
    return IncidentContextSnapshot(
        id=snapshot_id,
        scope=scope,
        incident_id=IncidentId(str(record.incident_id)),
        triage_run_id=TriageRunId(str(record.triage_run_id)),
        integration_id=IntegrationId(str(record.integration_id)),
        provider=record.provider,
        region=record.region,
        window_start=record.window_start,
        window_end=record.window_end,
        collected_at=record.collected_at,
        status=ContextCollectionStatus(record.status),
        policy_version=record.policy_version,
        diagnostics=tuple(
            CollectorDiagnostic(
                item["collector"],
                CollectorStatus(item["status"]),
                item.get("code"),
                item.get("summary"),
            )
            for item in record.diagnostics
        ),
        items=tuple(
            IncidentContextItem(
                id=IncidentContextItemId(str(item.id)),
                snapshot_id=snapshot_id,
                scope=scope,
                type=ContextItemType(item.type),
                source=item.source,
                observed_at=item.observed_at,
                content=dict(item.content),
                sequence=item.sequence,
                truncated=item.truncated,
            )
            for item in items
        ),
        truncated=record.truncated,
    )
