"""add membership RBAC and authorization grants

Revision ID: 8c4d2f7a9b10
Revises: 5e9c1a2d4b7f
Create Date: 2026-09-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8c4d2f7a9b10"
down_revision: Union[str, Sequence[str], None] = "5e9c1a2d4b7f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "organization_memberships",
        sa.Column(
            "workspace_access",
            sa.String(length=32),
            nullable=False,
            server_default="all",
        ),
    )
    op.alter_column(
        "organization_memberships", "workspace_access", server_default=None
    )
    op.create_unique_constraint(
        "uq_memberships_organization_id",
        "organization_memberships",
        ["organization_id", "id"],
    )
    op.create_check_constraint(
        "ck_memberships_workspace_access",
        "organization_memberships",
        "workspace_access IN ('all', 'restricted')",
    )
    op.create_check_constraint(
        "ck_memberships_owner_unrestricted",
        "organization_memberships",
        "role <> 'owner' OR workspace_access = 'all'",
    )

    op.create_table(
        "membership_workspace_grants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("membership_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_kind", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("actor_system_name", sa.String(length=120), nullable=True),
        sa.CheckConstraint(
            "actor_kind IN ('human', 'service_account', 'system')",
            name="ck_membership_workspace_grants_actor_kind",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "membership_id"],
            [
                "organization_memberships.organization_id",
                "organization_memberships.id",
            ],
            name="fk_membership_workspace_grants_membership_scope",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name="fk_membership_workspace_grants_workspace_scope",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "membership_id",
            "workspace_id",
            name="uq_membership_workspace_grants_membership_workspace",
        ),
    )
    op.create_index(
        "ix_membership_workspace_grants_scope",
        "membership_workspace_grants",
        ["organization_id", "workspace_id"],
    )

    op.create_table(
        "service_account_authorization_grants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("service_account_id", sa.UUID(), nullable=False),
        sa.Column(
            "permissions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("workspace_access", sa.String(length=32), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_kind", sa.String(length=32), nullable=True),
        sa.Column("revoked_by_id", sa.UUID(), nullable=True),
        sa.Column("revoked_by_system_name", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_kind", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("actor_system_name", sa.String(length=120), nullable=True),
        sa.CheckConstraint(
            "actor_kind IN ('human', 'service_account', 'system')",
            name="ck_service_account_authorization_grants_actor_kind",
        ),
        sa.CheckConstraint(
            "workspace_access IN ('all', 'restricted')",
            name="ck_service_account_authorization_grants_workspace_access",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(permissions) = 'array' AND jsonb_array_length(permissions) > 0",
            name="ck_service_account_authorization_grants_permissions",
        ),
        sa.CheckConstraint(
            "revoked_by_kind IS NULL OR revoked_by_kind IN ('human', 'service_account', 'system')",
            name="ck_service_account_authorization_grants_revoked_actor_kind",
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL AND revoked_by_kind IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by_kind IS NOT NULL)",
            name="ck_service_account_authorization_grants_revoked_attribution",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["service_account_id"], ["service_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "id",
            name="uq_service_account_authorization_grants_organization_id",
        ),
    )
    op.create_index(
        "uq_service_account_authorization_grants_active",
        "service_account_authorization_grants",
        ["organization_id", "service_account_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_service_account_authorization_grants_account",
        "service_account_authorization_grants",
        ["service_account_id", "revoked_at"],
    )

    op.create_table(
        "service_account_workspace_grants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("service_account_grant_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_kind", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("actor_system_name", sa.String(length=120), nullable=True),
        sa.CheckConstraint(
            "actor_kind IN ('human', 'service_account', 'system')",
            name="ck_service_account_workspace_grants_actor_kind",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "service_account_grant_id"],
            [
                "service_account_authorization_grants.organization_id",
                "service_account_authorization_grants.id",
            ],
            name="fk_service_account_workspace_grants_authorization_scope",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name="fk_service_account_workspace_grants_workspace_scope",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "service_account_grant_id",
            "workspace_id",
            name="uq_service_account_workspace_grants_grant_workspace",
        ),
    )
    op.create_index(
        "ix_service_account_workspace_grants_scope",
        "service_account_workspace_grants",
        ["organization_id", "workspace_id"],
    )

    organization_setting = (
        "NULLIF(current_setting('app.organization_id', true), '')::uuid"
    )
    for table_name in (
        "membership_workspace_grants",
        "service_account_authorization_grants",
        "service_account_workspace_grants",
    ):
        expression = f"organization_id = {organization_setting}"
        op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation ON "{table_name}" '
            f"USING ({expression}) WITH CHECK ({expression})"
        )

    actor_id = "NULLIF(current_setting('app.actor_id', true), '')::uuid"
    actor_kind = "current_setting('app.actor_kind', true)"
    op.execute(
        "CREATE POLICY actor_self_lookup ON organization_memberships FOR SELECT "
        f"USING ({actor_kind} = 'human' AND user_id = {actor_id})"
    )
    op.execute(
        "CREATE POLICY actor_self_lookup ON membership_workspace_grants FOR SELECT "
        "USING (EXISTS (SELECT 1 FROM organization_memberships membership "
        "WHERE membership.id = membership_id "
        "AND membership.organization_id = organization_id "
        f"AND {actor_kind} = 'human' AND membership.user_id = {actor_id}))"
    )
    op.execute(
        "CREATE POLICY actor_self_lookup ON service_account_authorization_grants "
        f"FOR SELECT USING ({actor_kind} = 'service_account' "
        f"AND service_account_id = {actor_id})"
    )
    op.execute(
        "CREATE POLICY actor_self_lookup ON service_account_workspace_grants FOR SELECT "
        "USING (EXISTS (SELECT 1 FROM service_account_authorization_grants grant_row "
        "WHERE grant_row.id = service_account_grant_id "
        "AND grant_row.organization_id = organization_id "
        f"AND {actor_kind} = 'service_account' "
        f"AND grant_row.service_account_id = {actor_id}))"
    )

    for table_name in (
        "membership_workspace_grants",
        "service_account_authorization_grants",
        "service_account_workspace_grants",
    ):
        op.execute(
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "{table_name}" TO aira_app'
        )


def downgrade() -> None:
    op.execute("DROP POLICY actor_self_lookup ON organization_memberships")
    op.drop_index(
        "ix_service_account_workspace_grants_scope",
        table_name="service_account_workspace_grants",
    )
    op.drop_table("service_account_workspace_grants")
    op.drop_index(
        "ix_service_account_authorization_grants_account",
        table_name="service_account_authorization_grants",
    )
    op.drop_index(
        "uq_service_account_authorization_grants_active",
        table_name="service_account_authorization_grants",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.drop_table("service_account_authorization_grants")
    op.drop_index(
        "ix_membership_workspace_grants_scope",
        table_name="membership_workspace_grants",
    )
    op.drop_table("membership_workspace_grants")
    op.drop_constraint(
        "ck_memberships_owner_unrestricted",
        "organization_memberships",
        type_="check",
    )
    op.drop_constraint(
        "ck_memberships_workspace_access",
        "organization_memberships",
        type_="check",
    )
    op.drop_constraint(
        "uq_memberships_organization_id",
        "organization_memberships",
        type_="unique",
    )
    op.drop_column("organization_memberships", "workspace_access")
