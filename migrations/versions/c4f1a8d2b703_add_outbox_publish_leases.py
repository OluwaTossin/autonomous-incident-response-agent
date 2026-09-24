"""add crash-safe outbox publication leases

Revision ID: c4f1a8d2b703
Revises: b7e2d4f9a301
Create Date: 2026-09-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4f1a8d2b703"
down_revision: Union[str, Sequence[str], None] = "b7e2d4f9a301"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "job_dispatch_outbox",
        sa.Column("claimed_by", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "job_dispatch_outbox",
        sa.Column("claim_token", sa.UUID(), nullable=True),
    )
    op.add_column(
        "job_dispatch_outbox",
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "job_dispatch_outbox",
        sa.Column(
            "publish_attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_check_constraint(
        "ck_job_dispatch_outbox_publish_attempts",
        "job_dispatch_outbox",
        "publish_attempt_count >= 0",
    )
    op.create_check_constraint(
        "ck_job_dispatch_outbox_claim_shape",
        "job_dispatch_outbox",
        "(claimed_by IS NULL AND claim_token IS NULL AND claim_expires_at IS NULL) OR "
        "(claimed_by IS NOT NULL AND claim_token IS NOT NULL "
        "AND claim_expires_at IS NOT NULL)",
    )
    op.alter_column(
        "job_dispatch_outbox", "publish_attempt_count", server_default=None
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_job_dispatch_outbox_claim_shape",
        "job_dispatch_outbox",
        type_="check",
    )
    op.drop_constraint(
        "ck_job_dispatch_outbox_publish_attempts",
        "job_dispatch_outbox",
        type_="check",
    )
    for column_name in (
        "publish_attempt_count",
        "claim_expires_at",
        "claim_token",
        "claimed_by",
    ):
        op.drop_column("job_dispatch_outbox", column_name)
