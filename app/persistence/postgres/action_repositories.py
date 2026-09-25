"""PostgreSQL persistence for immutable action proposals."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.domain.actions import ActionProposal
from app.domain.identifiers import ActionId, IncidentId, TriageRunId
from app.persistence.postgres.mappers import action_from_record, action_to_record
from app.persistence.postgres.models import ActionProposalRecord


class PostgresActionProposalRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_or_get(self, proposal: ActionProposal) -> tuple[ActionProposal, bool]:
        record = action_to_record(proposal)
        values = {
            column.name: getattr(record, column.name)
            for column in ActionProposalRecord.__table__.columns
        }
        inserted = self._session.scalar(
            insert(ActionProposalRecord)
            .values(**values)
            .on_conflict_do_nothing(constraint="uq_actions_run_result_identity")
            .returning(ActionProposalRecord.id)
        )
        if inserted is not None:
            return proposal, True
        existing = self._session.scalar(
            select(ActionProposalRecord).where(
                ActionProposalRecord.triage_run_id == UUID(str(proposal.triage_run.id)),
                ActionProposalRecord.source_result_hash == proposal.source_result_hash,
                ActionProposalRecord.normalized_action_hash
                == proposal.normalized_action_hash,
            )
        )
        if existing is None:
            raise RuntimeError(
                "Concurrent action proposal creation could not be resolved"
            )
        return action_from_record(existing), False

    def get(self, proposal_id: ActionId) -> ActionProposal | None:
        record = self._session.get(ActionProposalRecord, UUID(str(proposal_id)))
        return action_from_record(record) if record is not None else None

    def list_for_incident(self, incident_id: IncidentId) -> Sequence[ActionProposal]:
        records = self._session.scalars(
            select(ActionProposalRecord)
            .where(ActionProposalRecord.incident_id == UUID(str(incident_id)))
            .order_by(
                ActionProposalRecord.created_at.desc(),
                ActionProposalRecord.id.desc(),
            )
            .limit(100)
        ).all()
        return [action_from_record(record) for record in records]

    def list_for_triage_run(self, run_id: TriageRunId) -> Sequence[ActionProposal]:
        records = self._session.scalars(
            select(ActionProposalRecord)
            .where(ActionProposalRecord.triage_run_id == UUID(str(run_id)))
            .order_by(ActionProposalRecord.created_at, ActionProposalRecord.id)
            .limit(100)
        ).all()
        return [action_from_record(record) for record in records]
