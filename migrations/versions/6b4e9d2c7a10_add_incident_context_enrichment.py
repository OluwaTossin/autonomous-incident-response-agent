"""add bounded incident context snapshots

Revision ID: 6b4e9d2c7a10
Revises: 3a6f8c1d9e42
Create Date: 2026-09-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "6b4e9d2c7a10"
down_revision: Union[str, Sequence[str], None] = "3a6f8c1d9e42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "aws_integrations",
        sa.Column(
            "log_group_names",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.alter_column("aws_integrations", "log_group_names", server_default=None)
    op.create_table(
        "incident_context_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("incident_id", sa.UUID(), nullable=False),
        sa.Column("triage_run_id", sa.UUID(), nullable=False),
        sa.Column("integration_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("region", sa.String(64), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("policy_version", sa.String(80), nullable=False),
        sa.Column(
            "diagnostics", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "status IN ('complete', 'partial')", name="ck_context_snapshots_status"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "incident_id"],
            ["incidents.organization_id", "incidents.workspace_id", "incidents.id"],
            name="fk_context_snapshots_incident_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "triage_run_id"],
            [
                "triage_runs.organization_id",
                "triage_runs.workspace_id",
                "triage_runs.id",
            ],
            name="fk_context_snapshots_triage_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "integration_id"],
            [
                "aws_integrations.organization_id",
                "aws_integrations.workspace_id",
                "aws_integrations.id",
            ],
            name="fk_context_snapshots_integration_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "id",
            name="uq_context_snapshots_scope_id",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "triage_run_id",
            name="uq_context_snapshots_triage_run",
        ),
    )
    op.create_index(
        "ix_context_snapshots_incident",
        "incident_context_snapshots",
        ["incident_id", "collected_at"],
    )
    op.create_table(
        "incident_context_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("snapshot_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.CheckConstraint("sequence >= 0", name="ck_context_items_sequence"),
        sa.CheckConstraint(
            "type IN ('aws_cloudwatch_alarm', 'aws_cloudwatch_metric', 'aws_cloudwatch_log')",
            name="ck_context_items_type",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "snapshot_id"],
            [
                "incident_context_snapshots.organization_id",
                "incident_context_snapshots.workspace_id",
                "incident_context_snapshots.id",
            ],
            name="fk_context_items_snapshot_scope",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "snapshot_id",
            "sequence",
            name="uq_context_items_snapshot_sequence",
        ),
    )
    op.create_index(
        "ix_context_items_snapshot",
        "incident_context_items",
        ["snapshot_id", "sequence"],
    )
    expression = (
        "organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid "
        "AND workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid"
    )
    for table in ("incident_context_snapshots", "incident_context_items"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation ON "{table}" '
            f"USING ({expression}) WITH CHECK ({expression})"
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO aira_app")


def downgrade() -> None:
    op.drop_index("ix_context_items_snapshot", table_name="incident_context_items")
    op.drop_table("incident_context_items")
    op.drop_index(
        "ix_context_snapshots_incident", table_name="incident_context_snapshots"
    )
    op.drop_table("incident_context_snapshots")
    op.drop_column("aws_integrations", "log_group_names")
