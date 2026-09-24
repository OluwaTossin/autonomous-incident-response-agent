"""add verified knowledge bundle lifecycle

Revision ID: a3f8c2d9e601
Revises: e7b9c4d2a610
Create Date: 2026-09-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3f8c2d9e601"
down_revision: Union[str, Sequence[str], None] = "e7b9c4d2a610"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "knowledge_index_versions",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "knowledge_index_versions",
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "knowledge_index_versions",
        sa.Column("manifest_schema_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "knowledge_index_versions",
        sa.Column("artifact_prefix", sa.String(length=1024), nullable=True),
    )
    op.add_column(
        "knowledge_index_versions",
        sa.Column("manifest_checksum_sha256", sa.String(length=64), nullable=True),
    )

    op.execute(
        """
        UPDATE knowledge_index_versions
        SET state = 'failed',
            activated_at = NULL,
            failure_reason = 'Legacy index lacks a verified V3.9 bundle',
            updated_at = CURRENT_TIMESTAMP
        WHERE state IN ('active', 'inactive')
        """
    )
    op.drop_constraint(
        "ck_index_versions_state",
        "knowledge_index_versions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_index_versions_state",
        "knowledge_index_versions",
        "state IN ('building', 'ready', 'active', 'failed', 'inactive')",
    )
    op.create_check_constraint(
        "ck_index_versions_publication_state",
        "knowledge_index_versions",
        "((state IN ('ready', 'active', 'inactive')) "
        "AND published_at IS NOT NULL "
        "AND manifest_schema_version IS NOT NULL "
        "AND artifact_prefix IS NOT NULL "
        "AND manifest_checksum_sha256 IS NOT NULL) OR "
        "((state IN ('building', 'failed')) "
        "AND published_at IS NULL "
        "AND manifest_schema_version IS NULL "
        "AND artifact_prefix IS NULL "
        "AND manifest_checksum_sha256 IS NULL)",
    )
    op.create_check_constraint(
        "ck_index_versions_activation_state",
        "knowledge_index_versions",
        "(state IN ('active', 'inactive') AND activated_at IS NOT NULL) OR "
        "(state NOT IN ('active', 'inactive') AND activated_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_index_versions_superseded_state",
        "knowledge_index_versions",
        "(state = 'inactive' AND superseded_at IS NOT NULL) OR "
        "(state <> 'inactive' AND superseded_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_index_versions_manifest_schema_version",
        "knowledge_index_versions",
        "manifest_schema_version IS NULL OR manifest_schema_version > 0",
    )
    op.create_check_constraint(
        "ck_index_versions_manifest_checksum",
        "knowledge_index_versions",
        "manifest_checksum_sha256 IS NULL OR "
        "manifest_checksum_sha256 ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "ck_index_versions_artifact_prefix",
        "knowledge_index_versions",
        "artifact_prefix IS NULL OR length(btrim(artifact_prefix)) > 0",
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE knowledge_index_versions
        SET state = 'failed',
            activated_at = NULL,
            failure_reason = 'Verified bundle lifecycle removed during downgrade',
            published_at = NULL,
            superseded_at = NULL,
            manifest_schema_version = NULL,
            artifact_prefix = NULL,
            manifest_checksum_sha256 = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE state IN ('ready', 'active', 'inactive')
        """
    )
    for constraint_name in (
        "ck_index_versions_artifact_prefix",
        "ck_index_versions_manifest_checksum",
        "ck_index_versions_manifest_schema_version",
    ):
        op.drop_constraint(
            constraint_name,
            "knowledge_index_versions",
            type_="check",
        )
    op.drop_constraint(
        "ck_index_versions_superseded_state",
        "knowledge_index_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_index_versions_activation_state",
        "knowledge_index_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_index_versions_publication_state",
        "knowledge_index_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_index_versions_state",
        "knowledge_index_versions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_index_versions_state",
        "knowledge_index_versions",
        "state IN ('building', 'active', 'failed', 'inactive')",
    )
    for column_name in (
        "manifest_checksum_sha256",
        "artifact_prefix",
        "manifest_schema_version",
        "superseded_at",
        "published_at",
    ):
        op.drop_column("knowledge_index_versions", column_name)
