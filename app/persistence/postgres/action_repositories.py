"""PostgreSQL persistence for immutable action proposals."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.domain.actions import ActionProposal, Approval, ApprovalState
from app.domain.identifiers import ActionId, ApprovalId, IncidentId, TriageRunId
from app.persistence.postgres.mappers import (
    action_from_record,
    action_to_record,
    approval_from_record,
    approval_to_record,
)
from app.persistence.postgres.models import ActionProposalRecord, ApprovalRecord


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

    def get(
        self, proposal_id: ActionId, *, for_update: bool = False
    ) -> ActionProposal | None:
        statement = select(ActionProposalRecord).where(
            ActionProposalRecord.id == UUID(str(proposal_id))
        )
        if for_update:
            statement = statement.with_for_update()
        record = self._session.scalar(statement)
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


class PostgresApprovalRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_or_get_active(self, approval: Approval) -> tuple[Approval, bool]:
        record = approval_to_record(approval)
        values = {
            column.name: getattr(record, column.name)
            for column in ApprovalRecord.__table__.columns
        }
        inserted = self._session.scalar(
            insert(ApprovalRecord)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=(
                    ApprovalRecord.organization_id,
                    ApprovalRecord.workspace_id,
                    ApprovalRecord.action_id,
                ),
                index_where=ApprovalRecord.state == ApprovalState.REQUESTED.value,
            )
            .returning(ApprovalRecord.id)
        )
        if inserted is not None:
            return approval, True
        existing = self.get_active_for_proposal(approval.action.id)
        if existing is None:
            raise RuntimeError("Concurrent approval request could not be resolved")
        return existing, False

    def get(
        self, approval_id: ApprovalId, *, for_update: bool = False
    ) -> Approval | None:
        statement = select(ApprovalRecord).where(
            ApprovalRecord.id == UUID(str(approval_id))
        )
        if for_update:
            statement = statement.with_for_update()
        record = self._session.scalar(statement)
        return approval_from_record(record) if record is not None else None

    def get_active_for_proposal(
        self, proposal_id: ActionId, *, for_update: bool = False
    ) -> Approval | None:
        statement = select(ApprovalRecord).where(
            ApprovalRecord.action_id == UUID(str(proposal_id)),
            ApprovalRecord.state == ApprovalState.REQUESTED.value,
        )
        if for_update:
            statement = statement.with_for_update()
        record = self._session.scalar(statement)
        return approval_from_record(record) if record is not None else None

    def list_for_proposal(self, proposal_id: ActionId) -> Sequence[Approval]:
        records = self._session.scalars(
            select(ApprovalRecord)
            .where(ApprovalRecord.action_id == UUID(str(proposal_id)))
            .order_by(ApprovalRecord.created_at.desc(), ApprovalRecord.id.desc())
            .limit(100)
        ).all()
        return [approval_from_record(record) for record in records]

    def list_due(self, at: datetime, *, limit: int) -> Sequence[Approval]:
        records = self._session.scalars(
            select(ApprovalRecord)
            .where(
                ApprovalRecord.state == ApprovalState.REQUESTED.value,
                ApprovalRecord.expires_at <= at,
            )
            .order_by(ApprovalRecord.expires_at, ApprovalRecord.id)
            .with_for_update(skip_locked=True)
            .limit(limit)
        ).all()
        return [approval_from_record(record) for record in records]

    def save(self, approval: Approval, *, expected_version: int) -> None:
        decided = (
            approval_to_record(approval) if approval.decided_by is not None else None
        )
        result = self._session.execute(
            update(ApprovalRecord)
            .where(
                ApprovalRecord.id == UUID(str(approval.id)),
                ApprovalRecord.state_version == expected_version,
            )
            .values(
                state=approval.state.value,
                state_version=approval.state_version,
                updated_at=approval.updated_at,
                decided_by_kind=(decided.decided_by_kind if decided else None),
                decided_by_id=(decided.decided_by_id if decided else None),
                decided_by_system_name=(
                    decided.decided_by_system_name if decided else None
                ),
                decided_at=approval.decided_at,
                reason=approval.reason,
            )
        )
        if result.rowcount != 1:
            raise RuntimeError("Approval state changed concurrently")
