"""add immutable execution intents

Revision ID: b2c7e4f9a105
Revises: 7f3a9c2d1e84
Create Date: 2026-09-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "b2c7e4f9a105"
down_revision: Union[str, Sequence[str], None] = "7f3a9c2d1e84"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_approvals_scope_id",
        "approvals",
        ["organization_id", "workspace_id", "id"],
    )
    op.create_table(
        "execution_intents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("incident_id", sa.UUID(), nullable=False),
        sa.Column("triage_run_id", sa.UUID(), nullable=False),
        sa.Column("action_proposal_id", sa.UUID(), nullable=False),
        sa.Column("approval_id", sa.UUID(), nullable=False),
        sa.Column("proposal_schema_version", sa.Integer(), nullable=False),
        sa.Column("source_result_version", sa.Integer(), nullable=False),
        sa.Column("source_result_hash", sa.String(64), nullable=False),
        sa.Column("normalized_action_hash", sa.String(64), nullable=False),
        sa.Column("approval_state_version", sa.Integer(), nullable=False),
        sa.Column("approval_binding_hash", sa.String(64), nullable=False),
        sa.Column("approved_by_kind", sa.String(32), nullable=False),
        sa.Column("approved_by_id", sa.UUID(), nullable=True),
        sa.Column("approved_by_system_name", sa.String(120), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("connector_kind", sa.String(32), nullable=False),
        sa.Column("operation_kind", sa.String(80), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("target_type", sa.String(40), nullable=False),
        sa.Column("target_identifier", sa.Text(), nullable=False),
        sa.Column("target_provider", sa.String(80), nullable=False),
        sa.Column("target_provenance", sa.String(40), nullable=False),
        sa.Column("integration_id", sa.UUID(), nullable=True),
        sa.Column("target_account_id", sa.String(32), nullable=True),
        sa.Column("target_region", sa.String(64), nullable=True),
        sa.Column("parameters", postgresql.JSONB(), nullable=False),
        sa.Column("request_schema_version", sa.Integer(), nullable=False),
        sa.Column("risk_level", sa.String(32), nullable=False),
        sa.Column("reversibility", sa.String(32), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("lifecycle_state", sa.String(32), nullable=False),
        sa.Column("intent_hash", sa.String(64), nullable=False),
        sa.Column("execute_before", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_reason", sa.String(500), nullable=True),
        sa.Column("actor_kind", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("actor_system_name", sa.String(120), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name="fk_execution_intents_workspace_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "incident_id"],
            ["incidents.organization_id", "incidents.workspace_id", "incidents.id"],
            name="fk_execution_intents_incident_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "triage_run_id"],
            [
                "triage_runs.organization_id",
                "triage_runs.workspace_id",
                "triage_runs.id",
            ],
            name="fk_execution_intents_triage_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "action_proposal_id"],
            [
                "action_proposals.organization_id",
                "action_proposals.workspace_id",
                "action_proposals.id",
            ],
            name="fk_execution_intents_action_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "approval_id"],
            ["approvals.organization_id", "approvals.workspace_id", "approvals.id"],
            name="fk_execution_intents_approval_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "integration_id"],
            [
                "aws_integrations.organization_id",
                "aws_integrations.workspace_id",
                "aws_integrations.id",
            ],
            name="fk_execution_intents_integration_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "approval_id",
            name="uq_execution_intents_approval",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "intent_hash",
            name="uq_execution_intents_hash",
        ),
        sa.CheckConstraint(
            "connector_kind = 'internal' AND operation_kind = 'acknowledge_incident' AND provider = 'aira'",
            name="ck_execution_intents_allowlist",
        ),
        sa.CheckConstraint(
            "target_type = 'incident' AND target_provider = 'aira' AND target_provenance = 'incident' "
            "AND integration_id IS NULL AND target_account_id IS NULL AND target_region IS NULL "
            "AND target_identifier = incident_id::text",
            name="ck_execution_intents_target_authority",
        ),
        sa.CheckConstraint(
            "parameters = '{\"schema_version\": 1}'::jsonb",
            name="ck_execution_intents_parameters",
        ),
        sa.CheckConstraint(
            "proposal_schema_version = 1 AND source_result_version > 0 AND approval_state_version >= 2 "
            "AND request_schema_version = 1 AND policy_version = 1 AND state_version > 0",
            name="ck_execution_intents_versions",
        ),
        sa.CheckConstraint(
            "source_result_hash ~ '^[0-9a-f]{64}$' AND normalized_action_hash ~ '^[0-9a-f]{64}$' "
            "AND approval_binding_hash ~ '^[0-9a-f]{64}$' AND intent_hash ~ '^[0-9a-f]{64}$'",
            name="ck_execution_intents_hashes",
        ),
        sa.CheckConstraint(
            "approved_by_kind = 'human' AND approved_by_id IS NOT NULL AND approved_by_system_name IS NULL",
            name="ck_execution_intents_human_approver",
        ),
        sa.CheckConstraint(
            "actor_kind IN ('human', 'service_account', 'system')",
            name="ck_execution_intents_actor_kind",
        ),
        sa.CheckConstraint(
            "risk_level IN ('low', 'medium', 'high', 'critical')",
            name="ck_execution_intents_risk",
        ),
        sa.CheckConstraint(
            "reversibility IN ('reversible', 'partially_reversible', 'unknown')",
            name="ck_execution_intents_reversibility",
        ),
        sa.CheckConstraint(
            "lifecycle_state IN ('prepared', 'invalidated', 'cancelled')",
            name="ck_execution_intents_state",
        ),
        sa.CheckConstraint(
            "(lifecycle_state = 'prepared' AND terminal_at IS NULL AND terminal_reason IS NULL) OR "
            "(lifecycle_state IN ('invalidated', 'cancelled') AND terminal_at IS NOT NULL "
            "AND length(btrim(terminal_reason)) BETWEEN 1 AND 500)",
            name="ck_execution_intents_terminal_shape",
        ),
        sa.CheckConstraint(
            "approved_at <= created_at AND created_at <= updated_at AND execute_before > created_at",
            name="ck_execution_intents_times",
        ),
    )
    op.create_index(
        "ix_execution_intents_action_created",
        "execution_intents",
        ["organization_id", "workspace_id", "action_proposal_id", "created_at"],
    )
    op.create_index(
        "ix_execution_intents_scope_state",
        "execution_intents",
        ["organization_id", "workspace_id", "lifecycle_state"],
    )
    expression = (
        "organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid "
        "AND workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid"
    )
    op.execute('ALTER TABLE "execution_intents" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "execution_intents" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY tenant_isolation ON "execution_intents" '
        f"USING ({expression}) WITH CHECK ({expression})"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE execution_intents TO aira_app"
    )
    _create_immutability_trigger()


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM execution_intents) THEN
            RAISE EXCEPTION 'Downgrade would discard immutable execution intents';
          END IF;
        END
        $$
        """
    )
    op.execute("DROP TRIGGER execution_intents_immutable ON execution_intents")
    op.execute("DROP FUNCTION enforce_execution_intent_immutability()")
    op.drop_index("ix_execution_intents_scope_state", table_name="execution_intents")
    op.drop_index("ix_execution_intents_action_created", table_name="execution_intents")
    op.drop_table("execution_intents")
    op.drop_constraint("uq_approvals_scope_id", "approvals", type_="unique")


def _create_immutability_trigger() -> None:
    op.execute(
        """
        CREATE FUNCTION enforce_execution_intent_immutability() RETURNS trigger AS $$
        BEGIN
          IF (to_jsonb(NEW) - ARRAY['lifecycle_state', 'state_version', 'updated_at',
              'terminal_at', 'terminal_reason'])
             IS DISTINCT FROM
             (to_jsonb(OLD) - ARRAY['lifecycle_state', 'state_version', 'updated_at',
              'terminal_at', 'terminal_reason']) THEN
            RAISE EXCEPTION 'execution intent defining fields are immutable';
          END IF;
          IF OLD.lifecycle_state <> 'prepared'
             OR NEW.lifecycle_state NOT IN ('invalidated', 'cancelled')
             OR NEW.state_version <> OLD.state_version + 1 THEN
            RAISE EXCEPTION 'invalid execution intent lifecycle transition';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER execution_intents_immutable
        BEFORE UPDATE ON execution_intents
        FOR EACH ROW EXECUTE FUNCTION enforce_execution_intent_immutability();
        """
    )
