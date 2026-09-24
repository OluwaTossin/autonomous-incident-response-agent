"""add hosted document object storage lifecycle

Revision ID: e7b9c4d2a610
Revises: c2f6a8d1e4b9
Create Date: 2026-09-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7b9c4d2a610"
down_revision: Union[str, Sequence[str], None] = "c2f6a8d1e4b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "document_versions",
        sa.Column("original_filename", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column("storage_provider", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column("object_key", sa.String(length=1024), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column("state", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column("content_safety_state", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column("verified_checksum_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column("verified_size_bytes", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column("verified_media_type", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "document_versions", sa.Column("failure_reason", sa.Text(), nullable=True)
    )
    op.add_column(
        "document_versions",
        sa.Column("object_deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.execute(
        """
        UPDATE document_versions AS version
        SET original_filename = document.name,
            storage_provider = 'unmigrated',
            object_key = 'unmigrated/' || version.id::text,
            state = 'failed',
            content_safety_state = 'not_scanned',
            updated_at = version.created_at,
            failure_reason = 'Object metadata predates V3.7'
        FROM documents AS document
        WHERE document.id = version.document_id
          AND document.organization_id = version.organization_id
          AND document.workspace_id = version.workspace_id
        """
    )

    for column_name in (
        "original_filename",
        "storage_provider",
        "object_key",
        "state",
        "content_safety_state",
        "updated_at",
    ):
        op.alter_column("document_versions", column_name, nullable=False)

    op.create_unique_constraint(
        "uq_document_versions_object_key", "document_versions", ["object_key"]
    )
    op.create_check_constraint(
        "ck_document_versions_state",
        "document_versions",
        "state IN ('pending_upload', 'available', 'failed')",
    )
    op.create_check_constraint(
        "ck_document_versions_content_safety_state",
        "document_versions",
        "content_safety_state IN ('not_scanned', 'pending_scan', 'cleared', 'rejected')",
    )
    op.create_check_constraint(
        "ck_document_versions_verified_state",
        "document_versions",
        "(state = 'available' AND verified_checksum_sha256 IS NOT NULL "
        "AND verified_size_bytes IS NOT NULL AND verified_media_type IS NOT NULL "
        "AND finalized_at IS NOT NULL AND failure_reason IS NULL "
        "AND verified_checksum_sha256 = checksum_sha256 "
        "AND verified_size_bytes = size_bytes "
        "AND verified_media_type = media_type "
        "AND object_deleted_at IS NULL) OR "
        "(state <> 'available' AND verified_checksum_sha256 IS NULL "
        "AND verified_size_bytes IS NULL AND verified_media_type IS NULL "
        "AND finalized_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_document_versions_failure_state",
        "document_versions",
        "(state = 'failed' AND failure_reason IS NOT NULL) OR "
        "(state <> 'failed' AND failure_reason IS NULL)",
    )
    op.create_check_constraint(
        "ck_document_versions_deleted_state",
        "document_versions",
        "object_deleted_at IS NULL OR state = 'failed'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_document_versions_deleted_state", "document_versions", type_="check"
    )
    op.drop_constraint(
        "ck_document_versions_failure_state", "document_versions", type_="check"
    )
    op.drop_constraint(
        "ck_document_versions_verified_state", "document_versions", type_="check"
    )
    op.drop_constraint(
        "ck_document_versions_content_safety_state",
        "document_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_document_versions_state", "document_versions", type_="check"
    )
    op.drop_constraint(
        "uq_document_versions_object_key", "document_versions", type_="unique"
    )
    for column_name in (
        "object_deleted_at",
        "failure_reason",
        "finalized_at",
        "updated_at",
        "verified_media_type",
        "verified_size_bytes",
        "verified_checksum_sha256",
        "content_safety_state",
        "state",
        "object_key",
        "storage_provider",
        "original_filename",
    ):
        op.drop_column("document_versions", column_name)
