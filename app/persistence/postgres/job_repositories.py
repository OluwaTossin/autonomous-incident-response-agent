"""PostgreSQL repositories for the durable hosted job lifecycle."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.application.jobs import JobConflict, JobDispatch, JobListCursor
from app.domain.identifiers import JobId
from app.domain.operations import Job, JobState
from app.persistence.postgres.mappers import job_from_record, job_to_record
from app.persistence.postgres.models import JobDispatchRecord, JobRecord


class PostgresJobRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_or_get(self, job: Job) -> tuple[Job, bool]:
        record = job_to_record(job)
        values = {
            column.name: getattr(record, column.name)
            for column in JobRecord.__table__.columns
        }
        inserted = self._session.scalar(
            insert(JobRecord)
            .values(**values)
            .on_conflict_do_nothing(constraint="uq_jobs_idempotency")
            .returning(JobRecord.id)
        )
        if inserted is not None:
            return job, True
        existing = self._session.scalar(
            select(JobRecord).where(
                JobRecord.organization_id == UUID(str(job.scope.organization_id)),
                JobRecord.workspace_id == UUID(str(job.scope.workspace_id)),
                JobRecord.kind == job.kind.value,
                JobRecord.idempotency_key == job.idempotency_key,
            )
        )
        if existing is None:
            raise JobConflict("Concurrent idempotent job creation could not be resolved")
        return job_from_record(existing), False

    def get(self, job_id: JobId, *, for_update: bool = False) -> Job | None:
        statement = select(JobRecord).where(JobRecord.id == UUID(str(job_id)))
        if for_update:
            statement = statement.with_for_update()
        record = self._session.scalar(statement)
        return job_from_record(record) if record else None

    def list(
        self,
        *,
        limit: int,
        before: JobListCursor | None,
    ) -> list[Job]:
        statement = select(JobRecord)
        if before is not None:
            statement = statement.where(
                or_(
                    JobRecord.created_at < before.created_at,
                    and_(
                        JobRecord.created_at == before.created_at,
                        JobRecord.id < UUID(str(before.job_id)),
                    ),
                )
            )
        records = self._session.scalars(
            statement.order_by(JobRecord.created_at.desc(), JobRecord.id.desc()).limit(
                limit
            )
        ).all()
        return [job_from_record(record) for record in records]

    def list_expired(self, *, at, limit: int) -> list[Job]:
        records = self._session.scalars(
            select(JobRecord)
            .where(
                JobRecord.state == JobState.RUNNING.value,
                JobRecord.lease_expires_at <= at,
            )
            .order_by(JobRecord.lease_expires_at, JobRecord.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        return [job_from_record(record) for record in records]

    def save(self, job: Job, *, expected_version: int) -> None:
        record = job_to_record(job)
        excluded = {"id", "organization_id", "workspace_id", "created_at"}
        values = {
            column.name: getattr(record, column.name)
            for column in JobRecord.__table__.columns
            if column.name not in excluded
        }
        result = self._session.execute(
            update(JobRecord)
            .where(
                JobRecord.id == UUID(str(job.id)),
                JobRecord.organization_id == UUID(str(job.scope.organization_id)),
                JobRecord.workspace_id == UUID(str(job.scope.workspace_id)),
                JobRecord.state_version == expected_version,
            )
            .values(**values)
        )
        if result.rowcount != 1:
            raise JobConflict("Job state version is stale")
        self._session.flush()


class PostgresJobDispatchRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, job: Job, *, at) -> None:
        self._session.add(
            JobDispatchRecord(
                id=uuid4(),
                organization_id=UUID(str(job.scope.organization_id)),
                workspace_id=UUID(str(job.scope.workspace_id)),
                job_id=UUID(str(job.id)),
                dispatch_generation=job.dispatch_generation,
                available_at=job.available_at,
                created_at=at,
                published_at=None,
            )
        )
        self._session.flush()

    def list_unpublished(self, *, at, limit: int) -> list[JobDispatch]:
        records = self._session.scalars(
            select(JobDispatchRecord)
            .where(
                JobDispatchRecord.published_at.is_(None),
                JobDispatchRecord.available_at <= at,
            )
            .order_by(JobDispatchRecord.available_at, JobDispatchRecord.created_at)
            .limit(limit)
        ).all()
        return [
            JobDispatch(
                record.id,
                JobId(str(record.job_id)),
                record.dispatch_generation,
                record.available_at,
                record.created_at,
                record.published_at,
            )
            for record in records
        ]

    def mark_published(self, dispatch_id: UUID, *, at) -> bool:
        result = self._session.execute(
            update(JobDispatchRecord)
            .where(
                JobDispatchRecord.id == dispatch_id,
                JobDispatchRecord.published_at.is_(None),
            )
            .values(published_at=at)
        )
        self._session.flush()
        return result.rowcount == 1
