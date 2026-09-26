"""harden append-only audit and usage ledgers

Revision ID: 9e4b7a2c6d10
Revises: 2f9c7a6d4e18
Create Date: 2026-09-26
"""

from typing import Sequence, Union

from alembic import op


revision: str = "9e4b7a2c6d10"
down_revision: Union[str, Sequence[str], None] = "2f9c7a6d4e18"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table_name in ("audit_events", "usage_events"):
        op.execute(
            f'REVOKE UPDATE, DELETE, TRUNCATE ON TABLE "{table_name}" FROM aira_app'
        )


def downgrade() -> None:
    for table_name in ("audit_events", "usage_events"):
        op.execute(
            f'GRANT UPDATE, DELETE ON TABLE "{table_name}" TO aira_app'
        )
