"""add durable asynchronous job lifecycle

Revision ID: b7e2d4f9a301
Revises: a3f8c2d9e601
Create Date: 2026-09-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7e2d4f9a301"
down_revision: Union[str, Sequence[str], None] = "a3f8c2d9e601"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    additions = (
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("payload_version", sa.Integer(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=True),
        sa.Column("max_attempts", sa.Integer(), nullable=True),
        sa.Column("state_version", sa.Integer(), nullable=True),
        sa.Column("dispatch_generation", sa.Integer(), nullable=True),
        sa.Column("claimed_by", sa.String(length=120), nullable=True),
        sa.Column("claim_token", sa.UUID(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cancellation_requested_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("last_error_code", sa.String(length=120), nullable=True),
        sa.Column("last_error_category", sa.String(length=32), nullable=True),
        sa.Column("last_error_summary", sa.String(length=1000), nullable=True),
        sa.Column("last_error_retryable", sa.Boolean(), nullable=True),
        sa.Column("result_type", sa.String(length=80), nullable=True),
        sa.Column("result_id", sa.String(length=255), nullable=True),
        sa.Column(
            "result_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    for column in additions:
        op.add_column("jobs", column)

    op.execute(
        """
        UPDATE jobs
        SET idempotency_key = 'legacy:' || id::text,
            payload_version = 1,
            payload = jsonb_build_object(
                'subject_type', subject_type,
                'subject_id', subject_id
            ),
            payload_hash = md5(id::text) || md5(id::text),
            available_at = created_at,
            attempt_count = CASE WHEN state = 'pending' THEN 0 ELSE 1 END,
            max_attempts = 3,
            state_version = 1,
            dispatch_generation = 1,
            state = CASE WHEN state = 'running' THEN 'failed' ELSE state END,
            completed_at = CASE
                WHEN state = 'running' THEN COALESCE(completed_at, updated_at)
                ELSE completed_at
            END,
            failed_at = CASE
                WHEN state IN ('running', 'failed') THEN COALESCE(completed_at, updated_at)
                ELSE NULL
            END,
            cancelled_at = CASE
                WHEN state = 'cancelled' THEN completed_at
                ELSE NULL
            END,
            last_error_code = CASE
                WHEN state IN ('running', 'failed') THEN 'legacy_failure'
                ELSE NULL
            END,
            last_error_category = CASE
                WHEN state IN ('running', 'failed') THEN 'internal'
                ELSE NULL
            END,
            last_error_summary = CASE
                WHEN state IN ('running', 'failed')
                THEN COALESCE(error_message, 'Legacy running job had no durable lease')
                ELSE NULL
            END,
            last_error_retryable = CASE
                WHEN state IN ('running', 'failed') THEN false
                ELSE NULL
            END,
            result_type = CASE
                WHEN state = 'succeeded' THEN subject_type
                ELSE NULL
            END,
            result_id = CASE
                WHEN state = 'succeeded' THEN subject_id
                ELSE NULL
            END,
            result_metadata = CASE
                WHEN state = 'succeeded' THEN '{}'::jsonb
                ELSE NULL
            END
        """
    )
    for column_name in (
        "idempotency_key",
        "payload_version",
        "payload",
        "payload_hash",
        "available_at",
        "attempt_count",
        "max_attempts",
        "state_version",
        "dispatch_generation",
    ):
        op.alter_column("jobs", column_name, nullable=False)

    op.drop_index("ix_jobs_scope_state_created", table_name="jobs")
    op.create_unique_constraint(
        "uq_jobs_scope_id", "jobs", ["organization_id", "workspace_id", "id"]
    )
    op.create_unique_constraint(
        "uq_jobs_idempotency",
        "jobs",
        ["organization_id", "workspace_id", "kind", "idempotency_key"],
    )
    op.create_check_constraint(
        "ck_jobs_counters",
        "jobs",
        "payload_version > 0 AND max_attempts > 0 AND attempt_count >= 0 "
        "AND attempt_count <= max_attempts AND state_version > 0 "
        "AND dispatch_generation > 0",
    )
    op.create_check_constraint(
        "ck_jobs_payload_hash", "jobs", "payload_hash ~ '^[0-9a-f]{64}$'"
    )
    op.create_check_constraint(
        "ck_jobs_error_shape",
        "jobs",
        "(last_error_code IS NULL AND last_error_category IS NULL "
        "AND last_error_summary IS NULL AND last_error_retryable IS NULL) OR "
        "(last_error_code IS NOT NULL AND last_error_category IS NOT NULL "
        "AND last_error_summary IS NOT NULL AND last_error_retryable IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_jobs_error_category",
        "jobs",
        "last_error_category IS NULL OR last_error_category IN "
        "('transient', 'validation', 'authorization', 'configuration', 'internal')",
    )
    op.create_check_constraint(
        "ck_jobs_retryable_category",
        "jobs",
        "last_error_retryable IS NULL OR "
        "last_error_retryable = (last_error_category = 'transient')",
    )
    op.create_check_constraint(
        "ck_jobs_lifecycle_shape",
        "jobs",
        "((state = 'pending') AND claimed_by IS NULL AND claim_token IS NULL "
        "AND lease_expires_at IS NULL AND completed_at IS NULL "
        "AND cancelled_at IS NULL AND result_type IS NULL AND result_id IS NULL) OR "
        "((state = 'running') AND claimed_by IS NOT NULL AND claim_token IS NOT NULL "
        "AND lease_expires_at IS NOT NULL AND started_at IS NOT NULL "
        "AND completed_at IS NULL AND cancelled_at IS NULL "
        "AND result_type IS NULL AND result_id IS NULL) OR "
        "((state = 'succeeded') AND claimed_by IS NULL AND claim_token IS NULL "
        "AND lease_expires_at IS NULL AND started_at IS NOT NULL "
        "AND completed_at IS NOT NULL AND result_type IS NOT NULL "
        "AND result_id IS NOT NULL AND failed_at IS NULL AND cancelled_at IS NULL) OR "
        "((state = 'failed') AND claimed_by IS NULL AND claim_token IS NULL "
        "AND lease_expires_at IS NULL AND completed_at IS NOT NULL "
        "AND failed_at IS NOT NULL AND last_error_code IS NOT NULL "
        "AND result_type IS NULL AND result_id IS NULL) OR "
        "((state = 'cancelled') AND claimed_by IS NULL AND claim_token IS NULL "
        "AND lease_expires_at IS NULL AND completed_at IS NOT NULL "
        "AND cancelled_at IS NOT NULL AND result_type IS NULL AND result_id IS NULL)",
    )
    op.create_index(
        "ix_jobs_scope_created",
        "jobs",
        ["organization_id", "workspace_id", "created_at", "id"],
    )
    op.create_index(
        "ix_jobs_scope_runnable",
        "jobs",
        ["organization_id", "workspace_id", "state", "available_at", "id"],
    )
    op.create_index(
        "ix_jobs_lease_recovery",
        "jobs",
        ["organization_id", "workspace_id", "lease_expires_at"],
        postgresql_where=sa.text("state = 'running'"),
    )
    op.drop_column("jobs", "error_message")

    op.create_table(
        "job_dispatch_outbox",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("dispatch_generation", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "dispatch_generation > 0", name="ck_job_dispatch_outbox_generation"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "job_id"],
            ["jobs.organization_id", "jobs.workspace_id", "jobs.id"],
            name="fk_job_dispatch_outbox_job_scope",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "job_id",
            "dispatch_generation",
            name="uq_job_dispatch_outbox_generation",
        ),
    )
    op.create_index(
        "ix_job_dispatch_outbox_unpublished",
        "job_dispatch_outbox",
        ["available_at", "created_at"],
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.execute(
        """
        INSERT INTO job_dispatch_outbox (
            id, organization_id, workspace_id, job_id, dispatch_generation,
            available_at, created_at
        )
        SELECT gen_random_uuid(), organization_id, workspace_id, id,
               dispatch_generation, available_at, CURRENT_TIMESTAMP
        FROM jobs
        WHERE state = 'pending'
        """
    )
    organization_setting = (
        "NULLIF(current_setting('app.organization_id', true), '')::uuid"
    )
    workspace_setting = "NULLIF(current_setting('app.workspace_id', true), '')::uuid"
    expression = (
        f"organization_id = {organization_setting} "
        f"AND workspace_id = {workspace_setting}"
    )
    op.execute('ALTER TABLE "job_dispatch_outbox" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "job_dispatch_outbox" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY tenant_isolation ON "job_dispatch_outbox" '
        f"USING ({expression}) WITH CHECK ({expression})"
    )
    op.execute(
        'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "job_dispatch_outbox" TO aira_app'
    )


def downgrade() -> None:
    op.add_column("jobs", sa.Column("error_message", sa.Text(), nullable=True))
    op.execute(
        "UPDATE jobs SET error_message = last_error_summary WHERE state = 'failed'"
    )
    op.drop_index(
        "ix_job_dispatch_outbox_unpublished", table_name="job_dispatch_outbox"
    )
    op.drop_table("job_dispatch_outbox")
    op.create_index(
        "ix_jobs_scope_state_created",
        "jobs",
        ["organization_id", "workspace_id", "state", "created_at"],
    )
    for index_name in (
        "ix_jobs_lease_recovery",
        "ix_jobs_scope_runnable",
        "ix_jobs_scope_created",
    ):
        op.drop_index(index_name, table_name="jobs")
    for constraint_name in (
        "ck_jobs_lifecycle_shape",
        "ck_jobs_retryable_category",
        "ck_jobs_error_category",
        "ck_jobs_error_shape",
        "ck_jobs_payload_hash",
        "ck_jobs_counters",
        "uq_jobs_idempotency",
        "uq_jobs_scope_id",
    ):
        op.drop_constraint(constraint_name, "jobs", type_="check" if constraint_name.startswith("ck_") else "unique")
    for column_name in (
        "result_metadata",
        "result_id",
        "result_type",
        "last_error_retryable",
        "last_error_summary",
        "last_error_category",
        "last_error_code",
        "cancellation_requested_at",
        "cancelled_at",
        "failed_at",
        "lease_expires_at",
        "claim_token",
        "claimed_by",
        "dispatch_generation",
        "state_version",
        "max_attempts",
        "attempt_count",
        "available_at",
        "payload_hash",
        "payload",
        "payload_version",
        "idempotency_key",
    ):
        op.drop_column("jobs", column_name)
