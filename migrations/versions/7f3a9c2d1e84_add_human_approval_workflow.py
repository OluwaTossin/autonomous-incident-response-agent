"""add human approval workflow

Revision ID: 7f3a9c2d1e84
Revises: 4d8f2a1c9b73
Create Date: 2026-09-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "7f3a9c2d1e84"
down_revision: Union[str, Sequence[str], None] = "4d8f2a1c9b73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The foundation approval table was an unused skeleton. Refuse to reinterpret
    # records that lack an exact V3.19 proposal binding.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM approvals) THEN
            RAISE EXCEPTION 'V3.20 requires the pre-implementation approval scaffold to be empty';
          END IF;
        END
        $$
        """
    )
    op.drop_index("ix_approvals_action_state", table_name="approvals")
    op.drop_constraint("ck_approvals_decided_actor_kind", "approvals", type_="check")
    op.drop_constraint("ck_approvals_requested_actor_kind", "approvals", type_="check")

    op.add_column(
        "approvals", sa.Column("proposal_schema_version", sa.Integer(), nullable=False)
    )
    op.add_column(
        "approvals", sa.Column("source_result_version", sa.Integer(), nullable=False)
    )
    op.add_column(
        "approvals", sa.Column("source_result_hash", sa.String(64), nullable=False)
    )
    op.add_column(
        "approvals",
        sa.Column("normalized_action_hash", sa.String(64), nullable=False),
    )
    op.add_column("approvals", sa.Column("state_version", sa.Integer(), nullable=False))
    op.add_column(
        "approvals",
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
    )

    _create_checks()
    op.create_index(
        "ix_approvals_action_created",
        "approvals",
        ["action_id", "created_at"],
    )
    op.create_index(
        "uq_approvals_one_requested",
        "approvals",
        ["organization_id", "workspace_id", "action_id"],
        unique=True,
        postgresql_where=sa.text("state = 'requested'"),
    )
    op.create_index(
        "ix_approvals_scope_requested_expiry",
        "approvals",
        ["organization_id", "workspace_id", "expires_at"],
        postgresql_where=sa.text("state = 'requested'"),
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM approvals) THEN
            RAISE EXCEPTION 'Downgrade would discard durable human approvals';
          END IF;
        END
        $$
        """
    )
    for name in (
        "ix_approvals_scope_requested_expiry",
        "uq_approvals_one_requested",
        "ix_approvals_action_created",
    ):
        op.drop_index(name, table_name="approvals")
    for name in (
        "ck_approvals_reason_length",
        "ck_approvals_decision_expiry",
        "ck_approvals_distinct_decider",
        "ck_approvals_decision_fields",
        "ck_approvals_versions",
        "ck_approvals_expiry",
        "ck_approvals_human_decider",
        "ck_approvals_human_requester",
    ):
        op.drop_constraint(name, "approvals", type_="check")
    for column in (
        "requested_at",
        "state_version",
        "normalized_action_hash",
        "source_result_hash",
        "source_result_version",
        "proposal_schema_version",
    ):
        op.drop_column("approvals", column)
    op.create_check_constraint(
        "ck_approvals_requested_actor_kind",
        "approvals",
        "requested_by_kind IN ('human', 'service_account', 'system')",
    )
    op.create_check_constraint(
        "ck_approvals_decided_actor_kind",
        "approvals",
        "decided_by_kind IS NULL OR decided_by_kind IN "
        "('human', 'service_account', 'system')",
    )
    op.create_index("ix_approvals_action_state", "approvals", ["action_id", "state"])


def _create_checks() -> None:
    checks = {
        "ck_approvals_human_requester": (
            "requested_by_kind = 'human' AND requested_by_id IS NOT NULL "
            "AND requested_by_system_name IS NULL"
        ),
        "ck_approvals_human_decider": (
            "(decided_by_kind IS NULL AND decided_by_id IS NULL "
            "AND decided_by_system_name IS NULL) OR "
            "(decided_by_kind = 'human' AND decided_by_id IS NOT NULL "
            "AND decided_by_system_name IS NULL)"
        ),
        "ck_approvals_expiry": (
            "expires_at > requested_at AND requested_at = created_at"
        ),
        "ck_approvals_versions": (
            "state_version > 0 AND proposal_schema_version = 1 "
            "AND source_result_version > 0"
        ),
        "ck_approvals_decision_fields": (
            "(state = 'requested' AND decided_by_kind IS NULL "
            "AND decided_at IS NULL AND reason IS NULL) OR "
            "(state IN ('approved', 'cancelled') AND decided_by_kind = 'human' "
            "AND decided_at IS NOT NULL) OR "
            "(state = 'rejected' AND decided_by_kind = 'human' "
            "AND decided_at IS NOT NULL AND reason IS NOT NULL "
            "AND length(btrim(reason)) BETWEEN 1 AND 1000) OR "
            "(state = 'expired' AND decided_by_kind IS NULL "
            "AND decided_at IS NOT NULL)"
        ),
        "ck_approvals_reason_length": (
            "reason IS NULL OR length(btrim(reason)) BETWEEN 1 AND 1000"
        ),
        "ck_approvals_distinct_decider": (
            "state NOT IN ('approved', 'rejected') OR requested_by_id <> decided_by_id"
        ),
        "ck_approvals_decision_expiry": (
            "(state NOT IN ('approved', 'rejected') OR decided_at < expires_at) "
            "AND (state <> 'expired' OR decided_at >= expires_at)"
        ),
    }
    for name, expression in checks.items():
        op.create_check_constraint(name, "approvals", expression)
