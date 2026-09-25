"""add controlled action proposals

Revision ID: 4d8f2a1c9b73
Revises: 6b4e9d2c7a10
Create Date: 2026-09-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "4d8f2a1c9b73"
down_revision: Union[str, Sequence[str], None] = "6b4e9d2c7a10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # V3.2 created only an unused scaffold. Refuse to reinterpret any unexpected
    # records as safe controlled proposals.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM action_proposals) THEN
            RAISE EXCEPTION 'V3.19 requires the pre-implementation action scaffold to be empty';
          END IF;
        END
        $$
        """
    )
    op.drop_index("ix_actions_scope_state", table_name="action_proposals")
    op.drop_constraint("ck_actions_risk", "action_proposals", type_="check")
    op.drop_constraint("ck_actions_state", "action_proposals", type_="check")

    for column in ("action_type", "target", "risk", "state"):
        op.drop_column("action_proposals", column)
    for column in ("completed_at", "outcome_reference", "error_message"):
        op.drop_column("action_proposals", column)

    op.add_column(
        "action_proposals", sa.Column("proposal_type", sa.String(80), nullable=False)
    )
    op.add_column(
        "action_proposals", sa.Column("target_type", sa.String(40), nullable=False)
    )
    op.add_column(
        "action_proposals", sa.Column("target_identifier", sa.Text(), nullable=False)
    )
    op.add_column(
        "action_proposals", sa.Column("target_provider", sa.String(80), nullable=False)
    )
    op.add_column(
        "action_proposals",
        sa.Column("target_provenance", sa.String(40), nullable=False),
    )
    op.add_column(
        "action_proposals", sa.Column("integration_id", sa.UUID(), nullable=True)
    )
    op.add_column(
        "action_proposals", sa.Column("target_account_id", sa.String(32), nullable=True)
    )
    op.add_column(
        "action_proposals", sa.Column("target_region", sa.String(64), nullable=True)
    )
    op.add_column(
        "action_proposals", sa.Column("summary", sa.String(300), nullable=False)
    )
    op.add_column("action_proposals", sa.Column("rationale", sa.Text(), nullable=False))
    op.add_column(
        "action_proposals", sa.Column("risk_level", sa.String(32), nullable=False)
    )
    op.add_column(
        "action_proposals", sa.Column("reversibility", sa.String(32), nullable=False)
    )
    op.add_column(
        "action_proposals", sa.Column("policy_status", sa.String(32), nullable=False)
    )
    op.add_column(
        "action_proposals", sa.Column("policy_reason", sa.String(64), nullable=False)
    )
    op.add_column(
        "action_proposals", sa.Column("lifecycle_state", sa.String(32), nullable=False)
    )
    op.add_column(
        "action_proposals",
        sa.Column("source_result_version", sa.Integer(), nullable=False),
    )
    op.add_column(
        "action_proposals",
        sa.Column("source_result_hash", sa.String(64), nullable=False),
    )
    op.add_column(
        "action_proposals",
        sa.Column("normalized_action_hash", sa.String(64), nullable=False),
    )
    op.add_column(
        "action_proposals",
        sa.Column("proposal_schema_version", sa.Integer(), nullable=False),
    )
    op.add_column(
        "action_proposals", sa.Column("source_recommendation", sa.Text(), nullable=True)
    )
    op.alter_column("action_proposals", "incident_id", nullable=False)
    op.alter_column("action_proposals", "triage_run_id", nullable=False)

    op.create_foreign_key(
        "fk_actions_aws_integration_scope",
        "action_proposals",
        "aws_integrations",
        ["organization_id", "workspace_id", "integration_id"],
        ["organization_id", "workspace_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_actions_run_result_identity",
        "action_proposals",
        [
            "organization_id",
            "workspace_id",
            "triage_run_id",
            "source_result_hash",
            "normalized_action_hash",
        ],
    )
    _create_checks()
    op.create_index(
        "ix_actions_scope_state",
        "action_proposals",
        ["organization_id", "workspace_id", "lifecycle_state"],
    )
    op.create_index(
        "ix_actions_incident_created",
        "action_proposals",
        ["organization_id", "workspace_id", "incident_id", "created_at"],
    )
    op.create_index(
        "ix_actions_triage_run_created",
        "action_proposals",
        ["organization_id", "workspace_id", "triage_run_id", "created_at"],
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM action_proposals) THEN
            RAISE EXCEPTION 'Downgrade would discard controlled action proposals';
          END IF;
        END
        $$
        """
    )
    for name in (
        "ix_actions_triage_run_created",
        "ix_actions_incident_created",
        "ix_actions_scope_state",
    ):
        op.drop_index(name, table_name="action_proposals")
    for name in (
        "ck_actions_target_authority",
        "ck_actions_schema_versions",
        "ck_actions_policy_lifecycle",
        "ck_actions_lifecycle_state",
        "ck_actions_policy_status",
        "ck_actions_reversibility",
        "ck_actions_risk_level",
        "ck_actions_target_provenance",
        "ck_actions_target_type",
        "ck_actions_proposal_type",
    ):
        op.drop_constraint(name, "action_proposals", type_="check")
    op.drop_constraint(
        "uq_actions_run_result_identity", "action_proposals", type_="unique"
    )
    op.drop_constraint(
        "fk_actions_aws_integration_scope", "action_proposals", type_="foreignkey"
    )
    op.alter_column("action_proposals", "incident_id", nullable=True)
    op.alter_column("action_proposals", "triage_run_id", nullable=True)
    for column in (
        "source_recommendation",
        "proposal_schema_version",
        "normalized_action_hash",
        "source_result_hash",
        "source_result_version",
        "lifecycle_state",
        "policy_reason",
        "policy_status",
        "reversibility",
        "risk_level",
        "rationale",
        "summary",
        "target_region",
        "target_account_id",
        "integration_id",
        "target_provenance",
        "target_provider",
        "target_identifier",
        "target_type",
        "proposal_type",
    ):
        op.drop_column("action_proposals", column)
    op.add_column(
        "action_proposals", sa.Column("action_type", sa.String(120), nullable=False)
    )
    op.add_column("action_proposals", sa.Column("target", sa.Text(), nullable=False))
    op.add_column("action_proposals", sa.Column("risk", sa.String(32), nullable=False))
    op.add_column("action_proposals", sa.Column("state", sa.String(32), nullable=False))
    op.add_column(
        "action_proposals",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "action_proposals", sa.Column("outcome_reference", sa.Text(), nullable=True)
    )
    op.add_column(
        "action_proposals", sa.Column("error_message", sa.Text(), nullable=True)
    )
    op.create_check_constraint(
        "ck_actions_risk",
        "action_proposals",
        "risk IN ('informational', 'consequential')",
    )
    op.create_check_constraint(
        "ck_actions_state",
        "action_proposals",
        "state IN ('proposed', 'awaiting_approval', 'ready', 'executing', "
        "'succeeded', 'failed', 'rejected', 'expired', 'cancelled')",
    )
    op.create_index(
        "ix_actions_scope_state",
        "action_proposals",
        ["organization_id", "workspace_id", "state"],
    )


def _create_checks() -> None:
    checks = {
        "ck_actions_proposal_type": (
            "proposal_type IN ('acknowledge_incident', 'manual_investigation', "
            "'restart_workload', 'scale_workload', 'rollback_deployment')"
        ),
        "ck_actions_target_type": "target_type IN ('incident', 'service', 'aws_resource')",
        "ck_actions_target_provenance": (
            "target_provenance IN ('incident', 'operational_context', 'unknown')"
        ),
        "ck_actions_risk_level": "risk_level IN ('low', 'medium', 'high', 'critical')",
        "ck_actions_reversibility": (
            "reversibility IN ('reversible', 'partially_reversible', 'irreversible', 'unknown')"
        ),
        "ck_actions_policy_status": (
            "policy_status IN ('allowed_for_review', 'blocked', 'manual_only')"
        ),
        "ck_actions_lifecycle_state": (
            "lifecycle_state IN ('ready_for_review', 'blocked', 'manual_only', "
            "'superseded', 'cancelled')"
        ),
        "ck_actions_policy_lifecycle": (
            "(policy_status = 'allowed_for_review' AND lifecycle_state IN "
            "('ready_for_review', 'superseded', 'cancelled')) OR "
            "(policy_status = 'blocked' AND lifecycle_state IN "
            "('blocked', 'superseded', 'cancelled')) OR "
            "(policy_status = 'manual_only' AND lifecycle_state IN "
            "('manual_only', 'superseded', 'cancelled'))"
        ),
        "ck_actions_schema_versions": (
            "proposal_schema_version = 1 AND source_result_version > 0"
        ),
        "ck_actions_target_authority": (
            "(target_type = 'aws_resource' AND integration_id IS NOT NULL "
            "AND target_account_id IS NOT NULL AND target_region IS NOT NULL "
            "AND target_provenance = 'operational_context') OR "
            "(target_type <> 'aws_resource' AND integration_id IS NULL "
            "AND target_account_id IS NULL AND target_region IS NULL)"
        ),
    }
    for name, expression in checks.items():
        op.create_check_constraint(name, "action_proposals", expression)
