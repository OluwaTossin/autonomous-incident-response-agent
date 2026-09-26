"""add durable usage accounting and tenant quotas

Revision ID: 2f9c7a6d4e18
Revises: b2c7e4f9a105
Create Date: 2026-09-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2f9c7a6d4e18"
down_revision: Union[str, Sequence[str], None] = "b2c7e4f9a105"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_USAGE_TYPES = (
    "incident_created", "triage_requested", "triage_completed", "job_created",
    "document_bytes_stored", "document_version_created", "knowledge_index_build",
    "knowledge_bundle_bytes", "aws_integration_count", "alert_event_accepted",
    "context_log_bytes", "context_metric_points", "action_proposal_created",
    "approval_requested", "execution_intent_prepared", "llm_input_tokens",
    "llm_output_tokens",
)
_QUOTA_TYPES = (
    "triage_requests_per_hour", "concurrent_triage_runs", "document_count",
    "document_bytes", "active_aws_integrations", "alert_events_per_hour",
    "concurrent_index_builds", "execution_intents_per_hour",
)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.alter_column(
        "usage_events", "quantity", existing_type=sa.Float(), type_=sa.BigInteger(),
        postgresql_using="quantity::bigint", existing_nullable=False,
    )
    op.add_column("usage_events", sa.Column("source", sa.String(80), nullable=True))
    op.add_column("usage_events", sa.Column("source_reference", sa.String(255), nullable=True))
    op.add_column("usage_events", sa.Column("resource_type", sa.String(80), nullable=True))
    op.add_column("usage_events", sa.Column("resource_id", sa.String(255), nullable=True))
    op.execute("UPDATE usage_events SET source = 'legacy' WHERE source IS NULL")
    op.alter_column("usage_events", "source", nullable=False)
    op.create_check_constraint(
        "ck_usage_events_type", "usage_events", f"category IN ({_in(_USAGE_TYPES)})"
    )
    op.create_check_constraint(
        "ck_usage_events_unit", "usage_events", "unit IN ('event', 'byte', 'token', 'item')"
    )
    op.create_check_constraint(
        "ck_usage_events_integral", "usage_events", "quantity >= 0"
    )
    op.create_index(
        "uq_usage_events_source_reference", "usage_events",
        ["organization_id", "workspace_id", "category", "source", "source_reference"],
        unique=True, postgresql_where=sa.text("source_reference IS NOT NULL"),
    )
    op.create_index(
        "ix_usage_events_scope_type_occurred", "usage_events",
        ["organization_id", "workspace_id", "category", "occurred_at"],
    )

    op.create_table(
        "usage_counters",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("usage_type", sa.String(80), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name="fk_usage_counters_workspace_scope", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "usage_type", "window_start", "window_seconds"
        ),
        sa.CheckConstraint(f"usage_type IN ({_in(_USAGE_TYPES)})", name="ck_usage_counters_type"),
        sa.CheckConstraint("window_seconds IN (0, 3600)", name="ck_usage_counters_window"),
        sa.CheckConstraint("quantity >= 0", name="ck_usage_counters_quantity"),
    )
    op.create_index(
        "ix_usage_counters_scope_type", "usage_counters",
        ["organization_id", "workspace_id", "usage_type"],
    )

    op.create_table(
        "quota_policies",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=True),
        sa.Column("quota_type", sa.String(80), nullable=False),
        sa.Column("hard_limit", sa.BigInteger(), nullable=False),
        sa.Column("warning_percent", sa.Integer(), nullable=False),
        sa.Column("window_kind", sa.String(32), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_kind", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("actor_system_name", sa.String(120), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_quota_policies_organization", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name="fk_quota_policies_workspace_scope", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(f"quota_type IN ({_in(_QUOTA_TYPES)})", name="ck_quota_policies_type"),
        sa.CheckConstraint("hard_limit > 0", name="ck_quota_policies_limit"),
        sa.CheckConstraint("warning_percent BETWEEN 1 AND 100", name="ck_quota_policies_warning"),
        sa.CheckConstraint("window_kind IN ('lifetime', 'utc_hour', 'concurrent')", name="ck_quota_policies_window"),
        sa.CheckConstraint("policy_version > 0", name="ck_quota_policies_version"),
        sa.CheckConstraint("actor_kind IN ('human', 'service_account', 'system')", name="ck_quota_policies_actor_kind"),
    )
    op.create_index(
        "uq_quota_policies_organization", "quota_policies",
        ["organization_id", "quota_type"], unique=True,
        postgresql_where=sa.text("workspace_id IS NULL"),
    )
    op.create_index(
        "uq_quota_policies_workspace", "quota_policies",
        ["organization_id", "workspace_id", "quota_type"], unique=True,
        postgresql_where=sa.text("workspace_id IS NOT NULL"),
    )

    organization = "NULLIF(current_setting('app.organization_id', true), '')::uuid"
    workspace = "NULLIF(current_setting('app.workspace_id', true), '')::uuid"
    for table in ("usage_counters",):
        expression = f"organization_id = {organization} AND workspace_id = {workspace}"
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY tenant_isolation ON "{table}" USING ({expression}) WITH CHECK ({expression})')
        op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "{table}" TO aira_app')
    expression = f"organization_id = {organization} AND (workspace_id IS NULL OR workspace_id = {workspace})"
    op.execute('ALTER TABLE "quota_policies" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "quota_policies" FORCE ROW LEVEL SECURITY')
    op.execute(f'CREATE POLICY tenant_isolation ON "quota_policies" USING ({expression}) WITH CHECK ({expression})')
    op.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "quota_policies" TO aira_app')


def downgrade() -> None:
    op.drop_table("quota_policies")
    op.drop_index("ix_usage_counters_scope_type", table_name="usage_counters")
    op.drop_table("usage_counters")
    op.drop_index("ix_usage_events_scope_type_occurred", table_name="usage_events")
    op.drop_index("uq_usage_events_source_reference", table_name="usage_events")
    op.drop_constraint("ck_usage_events_integral", "usage_events", type_="check")
    op.drop_constraint("ck_usage_events_unit", "usage_events", type_="check")
    op.drop_constraint("ck_usage_events_type", "usage_events", type_="check")
    op.drop_column("usage_events", "resource_id")
    op.drop_column("usage_events", "resource_type")
    op.drop_column("usage_events", "source_reference")
    op.drop_column("usage_events", "source")
    op.alter_column(
        "usage_events", "quantity", existing_type=sa.BigInteger(), type_=sa.Float(),
        postgresql_using="quantity::double precision", existing_nullable=False,
    )
