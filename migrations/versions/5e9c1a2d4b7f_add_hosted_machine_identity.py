"""add hosted machine identity

Revision ID: 5e9c1a2d4b7f
Revises: 3541c01e5fb2
Create Date: 2026-09-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "5e9c1a2d4b7f"
down_revision: Union[str, Sequence[str], None] = "3541c01e5fb2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "identity_provider",
        existing_type=sa.String(length=80),
        type_=sa.String(length=255),
        existing_nullable=False,
    )
    op.create_table(
        "service_accounts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_by_kind", sa.String(length=32), nullable=True),
        sa.Column("disabled_by_id", sa.UUID(), nullable=True),
        sa.Column("disabled_by_system_name", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_kind", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("actor_system_name", sa.String(length=120), nullable=True),
        sa.CheckConstraint(
            "actor_kind IN ('human', 'service_account', 'system')",
            name="ck_service_accounts_actor_kind",
        ),
        sa.CheckConstraint(
            "disabled_by_kind IS NULL OR disabled_by_kind IN ('human', 'service_account', 'system')",
            name="ck_service_accounts_disabled_actor_kind",
        ),
        sa.CheckConstraint(
            "(disabled_at IS NULL AND disabled_by_kind IS NULL) OR "
            "(disabled_at IS NOT NULL AND disabled_by_kind IS NOT NULL)",
            name="ck_service_accounts_disabled_attribution",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_service_accounts_disabled",
        "service_accounts",
        ["disabled_at"],
        unique=False,
    )
    op.create_table(
        "service_account_credentials",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("service_account_id", sa.UUID(), nullable=False),
        sa.Column("lookup_id", sa.String(length=16), nullable=False),
        sa.Column("verifier", sa.LargeBinary(length=32), nullable=False),
        sa.Column("salt", sa.LargeBinary(length=16), nullable=False),
        sa.Column("algorithm", sa.String(length=32), nullable=False),
        sa.Column("created_by_kind", sa.String(length=32), nullable=False),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("created_by_system_name", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_kind", sa.String(length=32), nullable=True),
        sa.Column("revoked_by_id", sa.UUID(), nullable=True),
        sa.Column("revoked_by_system_name", sa.String(length=120), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "algorithm = 'scrypt-v1'",
            name="ck_service_account_credentials_algorithm",
        ),
        sa.CheckConstraint(
            "created_by_kind IN ('human', 'service_account', 'system')",
            name="ck_service_account_credentials_created_actor_kind",
        ),
        sa.CheckConstraint(
            "revoked_by_kind IS NULL OR revoked_by_kind IN ('human', 'service_account', 'system')",
            name="ck_service_account_credentials_revoked_actor_kind",
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL AND revoked_by_kind IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by_kind IS NOT NULL)",
            name="ck_service_account_credentials_revoked_attribution",
        ),
        sa.ForeignKeyConstraint(
            ["service_account_id"],
            ["service_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "lookup_id", name="uq_service_account_credentials_lookup"
        ),
    )
    op.create_index(
        "ix_service_account_credentials_account_active",
        "service_account_credentials",
        ["service_account_id", "revoked_at"],
        unique=False,
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE service_accounts TO aira_app"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
        "service_account_credentials TO aira_app"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_service_account_credentials_account_active",
        table_name="service_account_credentials",
    )
    op.drop_table("service_account_credentials")
    op.drop_index("ix_service_accounts_disabled", table_name="service_accounts")
    op.drop_table("service_accounts")
    op.alter_column(
        "users",
        "identity_provider",
        existing_type=sa.String(length=255),
        type_=sa.String(length=80),
        existing_nullable=False,
        postgresql_using="identity_provider::varchar(80)",
    )
