"""add async triage API lifecycle state and evidence provenance

Revision ID: d8a4c2e7f901
Revises: c4f1a8d2b703
Create Date: 2026-09-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d8a4c2e7f901"
down_revision: Union[str, Sequence[str], None] = "c4f1a8d2b703"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("triage_runs", sa.Column("error_code", sa.String(120)))
    op.add_column("triage_runs", sa.Column("error_category", sa.String(32)))
    op.add_column("triage_runs", sa.Column("error_retryable", sa.Boolean()))
    op.add_column("triage_runs", sa.Column("state_version", sa.Integer()))
    op.execute(
        """
        UPDATE triage_runs
        SET state_version = 1,
            error_code = CASE WHEN state = 'failed' THEN 'legacy_failure' END,
            error_category = CASE WHEN state = 'failed' THEN 'internal' END,
            error_retryable = CASE WHEN state = 'failed' THEN false END
        """
    )
    op.alter_column("triage_runs", "state_version", nullable=False)
    op.create_check_constraint(
        "ck_triage_runs_state_version", "triage_runs", "state_version > 0"
    )
    op.create_check_constraint(
        "ck_triage_runs_error_category",
        "triage_runs",
        "error_category IS NULL OR error_category IN "
        "('transient', 'validation', 'authorization', 'configuration', 'internal')",
    )
    op.create_check_constraint(
        "ck_triage_runs_error_shape",
        "triage_runs",
        "(error_code IS NULL AND error_category IS NULL AND error_retryable IS NULL) OR "
        "(error_code IS NOT NULL AND error_category IS NOT NULL "
        "AND error_retryable IS NOT NULL)",
    )
    op.create_index(
        "ix_triage_runs_scope_created",
        "triage_runs",
        ["organization_id", "workspace_id", "created_at", "id"],
    )

    op.add_column("evidence", sa.Column("sequence", sa.Integer()))
    op.add_column("evidence", sa.Column("origin", sa.String(32)))
    op.add_column("evidence", sa.Column("document_id", sa.String(255)))
    op.add_column("evidence", sa.Column("document_version_id", sa.String(255)))
    op.add_column(
        "evidence", sa.Column("knowledge_index_version_id", sa.String(255))
    )
    op.add_column("evidence", sa.Column("chunk_index", sa.Integer()))
    op.add_column("evidence", sa.Column("score", sa.Float()))
    op.execute(
        """
        WITH ordered AS (
            SELECT id, row_number() OVER (
                PARTITION BY organization_id, workspace_id, triage_run_id
                ORDER BY created_at, id
            ) - 1 AS sequence
            FROM evidence
        )
        UPDATE evidence
        SET sequence = ordered.sequence
        FROM ordered
        WHERE evidence.id = ordered.id
        """
    )
    op.alter_column("evidence", "sequence", nullable=False)
    op.create_check_constraint("ck_evidence_sequence", "evidence", "sequence >= 0")
    op.create_unique_constraint(
        "uq_evidence_triage_sequence",
        "evidence",
        ["organization_id", "workspace_id", "triage_run_id", "sequence"],
    )
    op.drop_index("ix_evidence_triage_run", table_name="evidence")
    op.create_index(
        "ix_evidence_triage_run", "evidence", ["triage_run_id", "sequence"]
    )

    op.drop_index("ix_incidents_scope_created", table_name="incidents")
    op.create_index(
        "ix_incidents_scope_created",
        "incidents",
        ["organization_id", "workspace_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_incidents_scope_created", table_name="incidents")
    op.create_index(
        "ix_incidents_scope_created",
        "incidents",
        ["organization_id", "workspace_id", "created_at"],
    )
    op.drop_index("ix_evidence_triage_run", table_name="evidence")
    op.create_index(
        "ix_evidence_triage_run", "evidence", ["triage_run_id", "created_at"]
    )
    op.drop_constraint("uq_evidence_triage_sequence", "evidence", type_="unique")
    op.drop_constraint("ck_evidence_sequence", "evidence", type_="check")
    for column in (
        "score",
        "chunk_index",
        "knowledge_index_version_id",
        "document_version_id",
        "document_id",
        "origin",
        "sequence",
    ):
        op.drop_column("evidence", column)
    op.drop_index("ix_triage_runs_scope_created", table_name="triage_runs")
    op.drop_constraint("ck_triage_runs_error_shape", "triage_runs", type_="check")
    op.drop_constraint("ck_triage_runs_error_category", "triage_runs", type_="check")
    op.drop_constraint("ck_triage_runs_state_version", "triage_runs", type_="check")
    for column in (
        "state_version",
        "error_retryable",
        "error_category",
        "error_code",
    ):
        op.drop_column("triage_runs", column)
