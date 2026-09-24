"""add hosted workspace state and typed configuration

Revision ID: c2f6a8d1e4b9
Revises: 8c4d2f7a9b10
Create Date: 2026-09-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c2f6a8d1e4b9"
down_revision: Union[str, Sequence[str], None] = "8c4d2f7a9b10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workspaces", sa.Column("description", sa.String(length=1000), nullable=True)
    )
    op.add_column(
        "workspaces",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.alter_column("workspaces", "version", server_default=None)

    op.create_table(
        "workspace_configurations",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("rag_top_k", sa.Integer(), nullable=False),
        sa.Column("llm_temperature", sa.Float(), nullable=False),
        sa.Column("updated_by_kind", sa.String(length=32), nullable=False),
        sa.Column("updated_by_id", sa.UUID(), nullable=True),
        sa.Column("updated_by_system_name", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "schema_version = 1",
            name="ck_workspace_configurations_schema_version",
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_workspace_configurations_version"
        ),
        sa.CheckConstraint(
            "rag_top_k BETWEEN 1 AND 64",
            name="ck_workspace_configurations_rag_top_k",
        ),
        sa.CheckConstraint(
            "llm_temperature BETWEEN 0 AND 2",
            name="ck_workspace_configurations_llm_temperature",
        ),
        sa.CheckConstraint(
            "updated_by_kind IN ('human', 'service_account', 'system')",
            name="ck_workspace_configurations_updated_actor_kind",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name="fk_workspace_configurations_workspace_scope",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id"),
    )
    op.create_index(
        "ix_workspace_configurations_scope",
        "workspace_configurations",
        ["organization_id", "workspace_id"],
    )

    op.execute(
        """
        INSERT INTO workspace_configurations (
            workspace_id,
            organization_id,
            schema_version,
            version,
            rag_top_k,
            llm_temperature,
            updated_by_kind,
            updated_by_id,
            updated_by_system_name,
            created_at,
            updated_at
        )
        SELECT
            id,
            organization_id,
            1,
            1,
            8,
            0.2,
            actor_kind,
            actor_id,
            actor_system_name,
            created_at,
            updated_at
        FROM workspaces
        """
    )

    organization_setting = (
        "NULLIF(current_setting('app.organization_id', true), '')::uuid"
    )
    workspace_setting = "NULLIF(current_setting('app.workspace_id', true), '')::uuid"
    expression = (
        f"organization_id = {organization_setting} "
        f"AND workspace_id = {workspace_setting}"
    )
    op.execute(
        'ALTER TABLE "workspace_configurations" ENABLE ROW LEVEL SECURITY'
    )
    op.execute(
        'ALTER TABLE "workspace_configurations" FORCE ROW LEVEL SECURITY'
    )
    op.execute(
        'CREATE POLICY tenant_isolation ON "workspace_configurations" '
        f"USING ({expression}) WITH CHECK ({expression})"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
        '"workspace_configurations" TO aira_app'
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workspace_configurations_scope",
        table_name="workspace_configurations",
    )
    op.drop_table("workspace_configurations")
    op.drop_column("workspaces", "version")
    op.drop_column("workspaces", "description")
