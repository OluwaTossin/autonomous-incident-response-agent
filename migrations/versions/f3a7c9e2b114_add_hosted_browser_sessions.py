"""add hosted browser login transactions and sessions

Revision ID: f3a7c9e2b114
Revises: d8a4c2e7f901
Create Date: 2026-09-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f3a7c9e2b114"
down_revision: Union[str, Sequence[str], None] = "d8a4c2e7f901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "oauth_login_transactions",
        sa.Column("id_hash", sa.String(64), primary_key=True),
        sa.Column("state_hash", sa.String(64), nullable=False),
        sa.Column("encrypted_payload", sa.LargeBinary(), nullable=False),
        sa.Column("return_path", sa.String(1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("expires_at > created_at", name="ck_oauth_login_expiry"),
    )
    op.create_index(
        "ix_oauth_login_transactions_expires",
        "oauth_login_transactions",
        ["expires_at"],
    )
    op.create_table(
        "browser_sessions",
        sa.Column("id_hash", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_issuer", sa.String(255), nullable=False),
        sa.Column("provider_subject", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("encrypted_tokens", sa.LargeBinary(), nullable=False),
        sa.Column("csrf_hash", sa.String(64), nullable=False),
        sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("inactivity_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "inactivity_expires_at > created_at AND absolute_expires_at > created_at",
            name="ck_browser_sessions_expiry",
        ),
        sa.CheckConstraint("version > 0", name="ck_browser_sessions_version"),
    )
    op.create_index(
        "ix_browser_sessions_user_active",
        "browser_sessions",
        ["user_id", "revoked_at"],
    )
    op.create_index(
        "ix_browser_sessions_absolute_expiry",
        "browser_sessions",
        ["absolute_expires_at"],
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
        "oauth_login_transactions, browser_sessions TO aira_app"
    )


def downgrade() -> None:
    op.drop_index("ix_browser_sessions_absolute_expiry", table_name="browser_sessions")
    op.drop_index("ix_browser_sessions_user_active", table_name="browser_sessions")
    op.drop_table("browser_sessions")
    op.drop_index(
        "ix_oauth_login_transactions_expires",
        table_name="oauth_login_transactions",
    )
    op.drop_table("oauth_login_transactions")
