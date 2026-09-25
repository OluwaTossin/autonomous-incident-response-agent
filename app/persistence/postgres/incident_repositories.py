"""PostgreSQL repositories for hosted incident and triage APIs."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import String, and_, delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.application.incidents import IncidentListCursor, TriageRunListCursor
from app.domain.identifiers import IncidentId, TriageRunId
from app.domain.incidents import Evidence, Feedback, Incident, IncidentState, TriageRun, TriageRunState
from app.domain.operations import Job, JobState
from app.persistence.postgres.mappers import (
    evidence_from_record,
    evidence_to_record,
    feedback_to_record,
    incident_from_record,
    incident_to_record,
    job_from_record,
    triage_run_from_record,
    triage_run_to_record,
)
from app.persistence.postgres.models import (
    EvidenceRecord,
    IncidentRecord,
    TriageRunRecord,
    JobRecord,
)


class PostgresHostedIncidentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_or_get(self, incident: Incident) -> tuple[Incident, bool]:
        record = incident_to_record(incident)
        if incident.source.external_id is None:
            self._session.add(record)
            self._session.flush()
            return incident, True
        values = {
            column.name: getattr(record, column.name)
            for column in IncidentRecord.__table__.columns
        }
        inserted = self._session.scalar(
            insert(IncidentRecord)
            .values(**values)
            .on_conflict_do_nothing(constraint="uq_incidents_source_external_id")
            .returning(IncidentRecord.id)
        )
        if inserted is not None:
            return incident, True
        existing = self._session.scalar(
            select(IncidentRecord).where(
                IncidentRecord.source_provider == incident.source.provider,
                IncidentRecord.source_external_id == incident.source.external_id,
            )
        )
        if existing is None:
            raise RuntimeError("Concurrent incident creation could not be resolved")
        return incident_from_record(existing), False

    def get(
        self, incident_id: IncidentId, *, for_update: bool = False
    ) -> Incident | None:
        statement = select(IncidentRecord).where(
            IncidentRecord.id == UUID(str(incident_id))
        )
        if for_update:
            statement = statement.with_for_update()
        record = self._session.scalar(statement)
        return incident_from_record(record) if record else None

    def list(
        self,
        *,
        limit: int,
        before: IncidentListCursor | None,
        state: IncidentState | None = None,
    ) -> Sequence[Incident]:
        statement = select(IncidentRecord)
        if state is not None:
            statement = statement.where(IncidentRecord.state == state.value)
        if before is not None:
            statement = statement.where(
                or_(
                    IncidentRecord.created_at < before.created_at,
                    and_(
                        IncidentRecord.created_at == before.created_at,
                        IncidentRecord.id < UUID(str(before.incident_id)),
                    ),
                )
            )
        records = self._session.scalars(
            statement.order_by(
                IncidentRecord.created_at.desc(), IncidentRecord.id.desc()
            ).limit(limit)
        ).all()
        return [incident_from_record(record) for record in records]

    def save(self, incident: Incident) -> None:
        record = incident_to_record(incident)
        result = self._session.execute(
            update(IncidentRecord)
            .where(IncidentRecord.id == UUID(str(incident.id)))
            .values(state=record.state, updated_at=record.updated_at)
        )
        if result.rowcount != 1:
            raise RuntimeError("Incident update conflicted")


class PostgresTriageRunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, run: TriageRun) -> None:
        self._session.add(triage_run_to_record(run))
        self._session.flush()

    def get(
        self, run_id: TriageRunId, *, for_update: bool = False
    ) -> TriageRun | None:
        statement = select(TriageRunRecord).where(
            TriageRunRecord.id == UUID(str(run_id))
        )
        if for_update:
            statement = statement.with_for_update()
        record = self._session.scalar(statement)
        return triage_run_from_record(record) if record else None

    def list(
        self,
        *,
        limit: int,
        before: TriageRunListCursor | None,
        incident_id: IncidentId | None = None,
        state: TriageRunState | None = None,
    ) -> Sequence[TriageRun]:
        statement = select(TriageRunRecord)
        if incident_id is not None:
            statement = statement.where(
                TriageRunRecord.incident_id == UUID(str(incident_id))
            )
        if state is not None:
            statement = statement.where(TriageRunRecord.state == state.value)
        if before is not None:
            statement = statement.where(
                or_(
                    TriageRunRecord.created_at < before.created_at,
                    and_(
                        TriageRunRecord.created_at == before.created_at,
                        TriageRunRecord.id < UUID(str(before.triage_run_id)),
                    ),
                )
            )
        records = self._session.scalars(
            statement.order_by(
                TriageRunRecord.created_at.desc(), TriageRunRecord.id.desc()
            ).limit(limit)
        ).all()
        return [triage_run_from_record(record) for record in records]

    def save(self, run: TriageRun, *, expected_version: int) -> None:
        record = triage_run_to_record(run)
        excluded = {
            "id",
            "organization_id",
            "workspace_id",
            "incident_id",
            "created_at",
        }
        values = {
            column.name: getattr(record, column.name)
            for column in TriageRunRecord.__table__.columns
            if column.name not in excluded
        }
        result = self._session.execute(
            update(TriageRunRecord)
            .where(
                TriageRunRecord.id == UUID(str(run.id)),
                TriageRunRecord.state_version == expected_version,
            )
            .values(**values)
        )
        if result.rowcount != 1:
            raise RuntimeError("Triage run state version is stale")
        self._session.flush()

    def list_inconsistent_jobs(self, *, limit: int) -> Sequence[tuple[TriageRun, Job]]:
        rows = self._session.execute(
            select(TriageRunRecord, JobRecord)
            .join(
                JobRecord,
                and_(
                    JobRecord.subject_type == "triage_run",
                    JobRecord.subject_id == TriageRunRecord.id.cast(String),
                ),
            )
            .where(
                or_(
                    and_(
                        TriageRunRecord.state == TriageRunState.RUNNING.value,
                        JobRecord.state.in_(
                            [
                                JobState.PENDING.value,
                                JobState.FAILED.value,
                                JobState.CANCELLED.value,
                            ]
                        ),
                    ),
                    and_(
                        TriageRunRecord.state == TriageRunState.QUEUED.value,
                        JobRecord.state == JobState.CANCELLED.value,
                    ),
                )
            )
            .order_by(TriageRunRecord.updated_at, TriageRunRecord.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        return [
            (triage_run_from_record(run), job_from_record(job))
            for run, job in rows
        ]


class PostgresEvidenceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_for_run(self, run_id: TriageRunId) -> Sequence[Evidence]:
        records = self._session.scalars(
            select(EvidenceRecord)
            .where(EvidenceRecord.triage_run_id == UUID(str(run_id)))
            .order_by(EvidenceRecord.sequence)
        ).all()
        return [evidence_from_record(record) for record in records]

    def replace_for_run(
        self, run_id: TriageRunId, evidence: Sequence[Evidence]
    ) -> None:
        self._session.execute(
            delete(EvidenceRecord).where(
                EvidenceRecord.triage_run_id == UUID(str(run_id))
            )
        )
        self._session.add_all(evidence_to_record(item) for item in evidence)
        self._session.flush()


class PostgresFeedbackRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, feedback: Feedback) -> None:
        self._session.add(feedback_to_record(feedback))
        self._session.flush()
