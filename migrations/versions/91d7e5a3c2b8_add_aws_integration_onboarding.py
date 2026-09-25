"""add AWS integration onboarding

Revision ID: 91d7e5a3c2b8
Revises: f3a7c9e2b114
Create Date: 2026-09-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "91d7e5a3c2b8"
down_revision: Union[str, Sequence[str], None] = "f3a7c9e2b114"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "aws_integrations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("aws_account_id", sa.String(12), nullable=False),
        sa.Column("role_arn", sa.String(600)),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("enabled_regions", postgresql.JSONB(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("verification", postgresql.JSONB()),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("disabled_at", sa.DateTime(timezone=True)),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_kind", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.UUID()),
        sa.Column("actor_system_name", sa.String(120)),
        sa.CheckConstraint(
            "actor_kind IN ('human', 'service_account', 'system')",
            name="ck_aws_integrations_actor_kind",
        ),
        sa.CheckConstraint(
            "state IN ('draft', 'pending_verification', 'ready', 'error', 'disabled')",
            name="ck_aws_integrations_state",
        ),
        sa.CheckConstraint("version > 0", name="ck_aws_integrations_version"),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name="fk_aws_integrations_workspace_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id", name="uq_aws_integrations_external_id"),
    )
    op.create_index(
        "ix_aws_integrations_scope_created",
        "aws_integrations",
        ["organization_id", "workspace_id", "created_at", "id"],
    )
    expression = (
        "organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid "
        "AND workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid"
    )
    op.execute('ALTER TABLE "aws_integrations" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "aws_integrations" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY tenant_isolation ON "aws_integrations" '
        f"USING ({expression}) WITH CHECK ({expression})"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE aws_integrations TO aira_app"
    )


def downgrade() -> None:
    op.drop_index("ix_aws_integrations_scope_created", table_name="aws_integrations")
    op.drop_table("aws_integrations")
