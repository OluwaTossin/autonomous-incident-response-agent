"""add CloudWatch alarm ingestion receipts and state

Revision ID: 3a6f8c1d9e42
Revises: 91d7e5a3c2b8
Create Date: 2026-09-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "3a6f8c1d9e42"
down_revision: Union[str, Sequence[str], None] = "91d7e5a3c2b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_aws_integrations_scope_id",
        "aws_integrations",
        ["organization_id", "workspace_id", "id"],
    )
    op.create_table(
        "alert_event_receipts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("integration_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("alarm_identity", sa.String(1000), nullable=False),
        sa.Column("alarm_identity_hash", sa.String(64), nullable=False),
        sa.Column("alarm_name", sa.String(255), nullable=False),
        sa.Column("account_id", sa.String(12), nullable=False),
        sa.Column("region", sa.String(64), nullable=False),
        sa.Column("alarm_state", sa.String(32), nullable=False),
        sa.Column("previous_alarm_state", sa.String(32), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("incident_id", sa.UUID()),
        sa.Column("triage_run_id", sa.UUID()),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("actor_kind", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.UUID()),
        sa.Column("actor_system_name", sa.String(120)),
        sa.CheckConstraint(
            "actor_kind IN ('human', 'service_account', 'system')",
            name="ck_alert_event_receipts_actor_kind",
        ),
        sa.CheckConstraint(
            "status IN ('accepted', 'ignored_stale', 'ignored_policy')",
            name="ck_alert_event_receipts_status",
        ),
        sa.CheckConstraint(
            "alarm_state IN ('ALARM', 'OK', 'INSUFFICIENT_DATA') "
            "AND previous_alarm_state IN ('ALARM', 'OK', 'INSUFFICIENT_DATA')",
            name="ck_alert_event_receipts_alarm_states",
        ),
        sa.CheckConstraint(
            "payload_hash ~ '^[0-9a-f]{64}$' "
            "AND alarm_identity_hash ~ '^[0-9a-f]{64}$'",
            name="ck_alert_event_receipts_hashes",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "integration_id"],
            [
                "aws_integrations.organization_id",
                "aws_integrations.workspace_id",
                "aws_integrations.id",
            ],
            name="fk_alert_event_receipts_integration_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "incident_id"],
            ["incidents.organization_id", "incidents.workspace_id", "incidents.id"],
            name="fk_alert_event_receipts_incident_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "triage_run_id"],
            [
                "triage_runs.organization_id",
                "triage_runs.workspace_id",
                "triage_runs.id",
            ],
            name="fk_alert_event_receipts_triage_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "integration_id",
            "event_id",
            name="uq_alert_event_receipts_delivery",
        ),
    )
    op.create_index(
        "ix_alert_event_receipts_integration_received",
        "alert_event_receipts",
        [
            "organization_id",
            "workspace_id",
            "integration_id",
            "received_at",
        ],
    )
    op.create_table(
        "aws_alarm_states",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("integration_id", sa.UUID(), nullable=False),
        sa.Column("alarm_identity", sa.String(1000), nullable=False),
        sa.Column("alarm_identity_hash", sa.String(64), nullable=False),
        sa.Column("alarm_name", sa.String(255), nullable=False),
        sa.Column("latest_event_id", sa.String(128), nullable=False),
        sa.Column("latest_state", sa.String(32), nullable=False),
        sa.Column("latest_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("incident_id", sa.UUID()),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "latest_state IN ('ALARM', 'OK', 'INSUFFICIENT_DATA')",
            name="ck_aws_alarm_states_state",
        ),
        sa.CheckConstraint(
            "alarm_identity_hash ~ '^[0-9a-f]{64}$'",
            name="ck_aws_alarm_states_identity_hash",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "integration_id"],
            [
                "aws_integrations.organization_id",
                "aws_integrations.workspace_id",
                "aws_integrations.id",
            ],
            name="fk_aws_alarm_states_integration_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "incident_id"],
            ["incidents.organization_id", "incidents.workspace_id", "incidents.id"],
            name="fk_aws_alarm_states_incident_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "integration_id",
            "alarm_identity_hash",
            name="uq_aws_alarm_states_identity",
        ),
    )
    op.create_index(
        "ix_aws_alarm_states_integration_updated",
        "aws_alarm_states",
        ["organization_id", "workspace_id", "integration_id", "updated_at"],
    )
    expression = (
        "organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid "
        "AND workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid"
    )
    for table in ("alert_event_receipts", "aws_alarm_states"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation ON "{table}" '
            f"USING ({expression}) WITH CHECK ({expression})"
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO aira_app")


def downgrade() -> None:
    op.drop_index(
        "ix_aws_alarm_states_integration_updated", table_name="aws_alarm_states"
    )
    op.drop_table("aws_alarm_states")
    op.drop_index(
        "ix_alert_event_receipts_integration_received",
        table_name="alert_event_receipts",
    )
    op.drop_table("alert_event_receipts")
    op.drop_constraint(
        "uq_aws_integrations_scope_id", "aws_integrations", type_="unique"
    )
