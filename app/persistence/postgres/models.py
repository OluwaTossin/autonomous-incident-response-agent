"""SQLAlchemy records for the hosted PostgreSQL schema.

These records deliberately mirror persistence concerns and never replace the
framework-independent objects under ``app.domain``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampColumns:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ActorColumns:
    actor_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    actor_system_name: Mapped[str | None] = mapped_column(String(120), nullable=True)


class WorkspaceTenantColumns:
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)


class ClassificationRetentionColumns:
    classification: Mapped[str] = mapped_column(String(32), nullable=False)
    retention_policy_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    retain_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CorrelationColumns:
    correlation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    correlation_incident_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    correlation_triage_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    correlation_job_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )


_ACTOR_CHECK = "actor_kind IN ('human', 'service_account', 'system')"
_CLASSIFICATION_CHECK = (
    "classification IN ('public', 'internal', 'confidential', 'restricted')"
)


class UserRecord(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint(
            "identity_provider", "provider_subject", name="uq_users_provider_subject"
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    identity_provider: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ServiceAccountRecord(Base, TimestampColumns, ActorColumns):
    __tablename__ = "service_accounts"
    __table_args__ = (
        CheckConstraint(_ACTOR_CHECK, name="ck_service_accounts_actor_kind"),
        CheckConstraint(
            "disabled_by_kind IS NULL OR disabled_by_kind IN ('human', 'service_account', 'system')",
            name="ck_service_accounts_disabled_actor_kind",
        ),
        CheckConstraint(
            "(disabled_at IS NULL AND disabled_by_kind IS NULL) OR "
            "(disabled_at IS NOT NULL AND disabled_by_kind IS NOT NULL)",
            name="ck_service_accounts_disabled_attribution",
        ),
        Index("ix_service_accounts_disabled", "disabled_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    disabled_by_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    disabled_by_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    disabled_by_system_name: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )


class ServiceAccountCredentialRecord(Base):
    __tablename__ = "service_account_credentials"
    __table_args__ = (
        UniqueConstraint("lookup_id", name="uq_service_account_credentials_lookup"),
        CheckConstraint(
            "algorithm = 'scrypt-v1'", name="ck_service_account_credentials_algorithm"
        ),
        CheckConstraint(
            "created_by_kind IN ('human', 'service_account', 'system')",
            name="ck_service_account_credentials_created_actor_kind",
        ),
        CheckConstraint(
            "revoked_by_kind IS NULL OR revoked_by_kind IN ('human', 'service_account', 'system')",
            name="ck_service_account_credentials_revoked_actor_kind",
        ),
        CheckConstraint(
            "(revoked_at IS NULL AND revoked_by_kind IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by_kind IS NOT NULL)",
            name="ck_service_account_credentials_revoked_attribution",
        ),
        Index(
            "ix_service_account_credentials_account_active",
            "service_account_id",
            "revoked_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    service_account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("service_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    lookup_id: Mapped[str] = mapped_column(String(16), nullable=False)
    verifier: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    salt: Mapped[bytes] = mapped_column(LargeBinary(16), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    created_by_system_name: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    revoked_by_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    revoked_by_system_name: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class OrganizationRecord(Base, TimestampColumns, ActorColumns):
    __tablename__ = "organizations"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_organizations_slug"),
        CheckConstraint(
            "state IN ('active', 'archived')", name="ck_organizations_state"
        ),
        CheckConstraint(_ACTOR_CHECK, name="ck_organizations_actor_kind"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)


class OrganizationMembershipRecord(Base, TimestampColumns, ActorColumns):
    __tablename__ = "organization_memberships"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "user_id", name="uq_memberships_organization_user"
        ),
        UniqueConstraint(
            "organization_id", "id", name="uq_memberships_organization_id"
        ),
        CheckConstraint(
            "role IN ('owner', 'admin', 'operator', 'viewer')",
            name="ck_memberships_role",
        ),
        CheckConstraint(
            "state IN ('invited', 'active', 'suspended', 'revoked')",
            name="ck_memberships_state",
        ),
        CheckConstraint(
            "workspace_access IN ('all', 'restricted')",
            name="ck_memberships_workspace_access",
        ),
        CheckConstraint(
            "role <> 'owner' OR workspace_access = 'all'",
            name="ck_memberships_owner_unrestricted",
        ),
        CheckConstraint(_ACTOR_CHECK, name="ck_memberships_actor_kind"),
        Index("ix_memberships_user_state", "user_id", "state"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    workspace_access: Mapped[str] = mapped_column(String(32), nullable=False)


class WorkspaceRecord(Base, TimestampColumns, ActorColumns):
    __tablename__ = "workspaces"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "slug", name="uq_workspaces_organization_slug"
        ),
        UniqueConstraint("organization_id", "id", name="uq_workspaces_organization_id"),
        CheckConstraint("state IN ('active', 'archived')", name="ck_workspaces_state"),
        CheckConstraint(_ACTOR_CHECK, name="ck_workspaces_actor_kind"),
        Index("ix_workspaces_organization_state", "organization_id", "state"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class WorkspaceConfigurationRecord(Base):
    __tablename__ = "workspace_configurations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name="fk_workspace_configurations_workspace_scope",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "schema_version = 1",
            name="ck_workspace_configurations_schema_version",
        ),
        CheckConstraint(
            "version >= 1", name="ck_workspace_configurations_version"
        ),
        CheckConstraint(
            "rag_top_k BETWEEN 1 AND 64",
            name="ck_workspace_configurations_rag_top_k",
        ),
        CheckConstraint(
            "llm_temperature BETWEEN 0 AND 2",
            name="ck_workspace_configurations_llm_temperature",
        ),
        CheckConstraint(
            "updated_by_kind IN ('human', 'service_account', 'system')",
            name="ck_workspace_configurations_updated_actor_kind",
        ),
        Index(
            "ix_workspace_configurations_scope",
            "organization_id",
            "workspace_id",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    rag_top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    llm_temperature: Mapped[float] = mapped_column(Float, nullable=False)
    updated_by_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_by_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    updated_by_system_name: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class MembershipWorkspaceGrantRecord(Base, WorkspaceTenantColumns, ActorColumns):
    __tablename__ = "membership_workspace_grants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "membership_id"],
            ["organization_memberships.organization_id", "organization_memberships.id"],
            name="fk_membership_workspace_grants_membership_scope",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name="fk_membership_workspace_grants_workspace_scope",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "membership_id",
            "workspace_id",
            name="uq_membership_workspace_grants_membership_workspace",
        ),
        CheckConstraint(
            _ACTOR_CHECK, name="ck_membership_workspace_grants_actor_kind"
        ),
        Index(
            "ix_membership_workspace_grants_scope",
            "organization_id",
            "workspace_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    membership_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ServiceAccountAuthorizationGrantRecord(
    Base, TimestampColumns, ActorColumns
):
    __tablename__ = "service_account_authorization_grants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["service_account_id"], ["service_accounts.id"], ondelete="CASCADE"
        ),
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_service_account_authorization_grants_organization_id",
        ),
        CheckConstraint(
            "workspace_access IN ('all', 'restricted')",
            name="ck_service_account_authorization_grants_workspace_access",
        ),
        CheckConstraint(
            "jsonb_typeof(permissions) = 'array' AND jsonb_array_length(permissions) > 0",
            name="ck_service_account_authorization_grants_permissions",
        ),
        CheckConstraint(
            _ACTOR_CHECK, name="ck_service_account_authorization_grants_actor_kind"
        ),
        CheckConstraint(
            "revoked_by_kind IS NULL OR revoked_by_kind IN ('human', 'service_account', 'system')",
            name="ck_service_account_authorization_grants_revoked_actor_kind",
        ),
        CheckConstraint(
            "(revoked_at IS NULL AND revoked_by_kind IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by_kind IS NOT NULL)",
            name="ck_service_account_authorization_grants_revoked_attribution",
        ),
        Index(
            "uq_service_account_authorization_grants_active",
            "organization_id",
            "service_account_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index(
            "ix_service_account_authorization_grants_account",
            "service_account_id",
            "revoked_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    service_account_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    permissions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    workspace_access: Mapped[str] = mapped_column(String(32), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    revoked_by_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    revoked_by_system_name: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )


class ServiceAccountWorkspaceGrantRecord(
    Base, WorkspaceTenantColumns, ActorColumns
):
    __tablename__ = "service_account_workspace_grants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "service_account_grant_id"],
            [
                "service_account_authorization_grants.organization_id",
                "service_account_authorization_grants.id",
            ],
            name="fk_service_account_workspace_grants_authorization_scope",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name="fk_service_account_workspace_grants_workspace_scope",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "service_account_grant_id",
            "workspace_id",
            name="uq_service_account_workspace_grants_grant_workspace",
        ),
        CheckConstraint(
            _ACTOR_CHECK, name="ck_service_account_workspace_grants_actor_kind"
        ),
        Index(
            "ix_service_account_workspace_grants_scope",
            "organization_id",
            "workspace_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    service_account_grant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class IncidentRecord(
    Base,
    WorkspaceTenantColumns,
    TimestampColumns,
    ActorColumns,
    ClassificationRetentionColumns,
    CorrelationColumns,
):
    __tablename__ = "incidents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name="fk_incidents_workspace_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "organization_id", "workspace_id", "id", name="uq_incidents_scope_id"
        ),
        UniqueConstraint(
            "organization_id",
            "workspace_id",
            "source_provider",
            "source_external_id",
            name="uq_incidents_source_external_id",
        ),
        CheckConstraint(
            "state IN ('open', 'investigating', 'resolved', 'closed')",
            name="ck_incidents_state",
        ),
        CheckConstraint(_ACTOR_CHECK, name="ck_incidents_actor_kind"),
        CheckConstraint(_CLASSIFICATION_CHECK, name="ck_incidents_classification"),
        Index(
            "ix_incidents_scope_created",
            "organization_id",
            "workspace_id",
            "created_at",
            "id",
        ),
        Index("ix_incidents_scope_state", "organization_id", "workspace_id", "state"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_provider: Mapped[str] = mapped_column(String(80), nullable=False)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)


class TriageRunRecord(
    Base,
    WorkspaceTenantColumns,
    TimestampColumns,
    ActorColumns,
    ClassificationRetentionColumns,
    CorrelationColumns,
):
    __tablename__ = "triage_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name="fk_triage_runs_workspace_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "incident_id"],
            ["incidents.organization_id", "incidents.workspace_id", "incidents.id"],
            name="fk_triage_runs_incident_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "organization_id", "workspace_id", "id", name="uq_triage_runs_scope_id"
        ),
        CheckConstraint("state_version > 0", name="ck_triage_runs_state_version"),
        CheckConstraint(
            "state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_triage_runs_state",
        ),
        CheckConstraint(_ACTOR_CHECK, name="ck_triage_runs_actor_kind"),
        CheckConstraint(_CLASSIFICATION_CHECK, name="ck_triage_runs_classification"),
        Index("ix_triage_runs_incident_created", "incident_id", "created_at"),
        Index("ix_triage_runs_scope_state", "organization_id", "workspace_id", "state"),
        Index(
            "ix_triage_runs_scope_created",
            "organization_id",
            "workspace_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    incident_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_retryable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)


class EvidenceRecord(Base, WorkspaceTenantColumns, ClassificationRetentionColumns):
    __tablename__ = "evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name="fk_evidence_workspace_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "triage_run_id"],
            [
                "triage_runs.organization_id",
                "triage_runs.workspace_id",
                "triage_runs.id",
            ],
            name="fk_evidence_triage_run_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "type IN ('log', 'incident', 'runbook', 'knowledge', 'decision', 'metric', 'alert', 'other')",
            name="ck_evidence_type",
        ),
        CheckConstraint(_CLASSIFICATION_CHECK, name="ck_evidence_classification"),
        UniqueConstraint(
            "organization_id",
            "workspace_id",
            "triage_run_id",
            "sequence",
            name="uq_evidence_triage_sequence",
        ),
        CheckConstraint("sequence >= 0", name="ck_evidence_sequence"),
        Index("ix_evidence_triage_run", "triage_run_id", "sequence"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    triage_run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    origin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    document_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    document_version_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    knowledge_index_version_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    chunk_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class FeedbackRecord(Base, WorkspaceTenantColumns, ClassificationRetentionColumns):
    __tablename__ = "feedback"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name="fk_feedback_workspace_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "triage_run_id"],
            [
                "triage_runs.organization_id",
                "triage_runs.workspace_id",
                "triage_runs.id",
            ],
            name="fk_feedback_triage_run_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "submitted_by_kind IN ('human', 'service_account', 'system')",
            name="ck_feedback_actor_kind",
        ),
        CheckConstraint(_CLASSIFICATION_CHECK, name="ck_feedback_classification"),
        Index("ix_feedback_triage_run_created", "triage_run_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    triage_run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    submitted_by_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    submitted_by_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    submitted_by_system_name: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    diagnosis_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    actions_useful: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class DocumentRecord(
    Base,
    WorkspaceTenantColumns,
    TimestampColumns,
    ActorColumns,
    ClassificationRetentionColumns,
):
    __tablename__ = "documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name="fk_documents_workspace_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "organization_id", "workspace_id", "id", name="uq_documents_scope_id"
        ),
        CheckConstraint(
            "category IN ('runbook', 'incident', 'log', 'knowledge', 'other')",
            name="ck_documents_category",
        ),
        CheckConstraint(
            "state IN ('pending_upload', 'available', 'failed', 'archived')",
            name="ck_documents_state",
        ),
        CheckConstraint(_ACTOR_CHECK, name="ck_documents_actor_kind"),
        CheckConstraint(_CLASSIFICATION_CHECK, name="ck_documents_classification"),
        Index("ix_documents_scope_state", "organization_id", "workspace_id", "state"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class DocumentVersionRecord(Base, WorkspaceTenantColumns, ActorColumns):
    __tablename__ = "document_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name="fk_document_versions_workspace_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "document_id"],
            ["documents.organization_id", "documents.workspace_id", "documents.id"],
            name="fk_document_versions_document_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "organization_id",
            "workspace_id",
            "id",
            name="uq_document_versions_scope_id",
        ),
        UniqueConstraint(
            "document_id", "version_number", name="uq_document_versions_number"
        ),
        CheckConstraint("version_number > 0", name="ck_document_versions_number"),
        CheckConstraint("size_bytes >= 0", name="ck_document_versions_size"),
        CheckConstraint(
            "state IN ('pending_upload', 'available', 'failed')",
            name="ck_document_versions_state",
        ),
        CheckConstraint(
            "content_safety_state IN ('not_scanned', 'pending_scan', 'cleared', 'rejected')",
            name="ck_document_versions_content_safety_state",
        ),
        CheckConstraint(
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
            name="ck_document_versions_verified_state",
        ),
        CheckConstraint(
            "(state = 'failed' AND failure_reason IS NOT NULL) OR "
            "(state <> 'failed' AND failure_reason IS NULL)",
            name="ck_document_versions_failure_state",
        ),
        CheckConstraint(
            "object_deleted_at IS NULL OR state = 'failed'",
            name="ck_document_versions_deleted_state",
        ),
        CheckConstraint(_ACTOR_CHECK, name="ck_document_versions_actor_kind"),
        Index("ix_document_versions_document", "document_id", "version_number"),
        UniqueConstraint("object_key", name="uq_document_versions_object_key"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    content_safety_state: Mapped[str] = mapped_column(String(32), nullable=False)
    verified_checksum_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    verified_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    verified_media_type: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    object_deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class KnowledgeIndexVersionRecord(
    Base, WorkspaceTenantColumns, TimestampColumns, ActorColumns
):
    __tablename__ = "knowledge_index_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name="fk_index_versions_workspace_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "organization_id", "workspace_id", "id", name="uq_index_versions_scope_id"
        ),
        CheckConstraint(
            "state IN ('building', 'ready', 'active', 'failed', 'inactive')",
            name="ck_index_versions_state",
        ),
        CheckConstraint(
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
            name="ck_index_versions_publication_state",
        ),
        CheckConstraint(
            "(state IN ('active', 'inactive') AND activated_at IS NOT NULL) OR "
            "(state NOT IN ('active', 'inactive') AND activated_at IS NULL)",
            name="ck_index_versions_activation_state",
        ),
        CheckConstraint(
            "(state = 'inactive' AND superseded_at IS NOT NULL) OR "
            "(state <> 'inactive' AND superseded_at IS NULL)",
            name="ck_index_versions_superseded_state",
        ),
        CheckConstraint(
            "manifest_schema_version IS NULL OR manifest_schema_version > 0",
            name="ck_index_versions_manifest_schema_version",
        ),
        CheckConstraint(
            "manifest_checksum_sha256 IS NULL OR "
            "manifest_checksum_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_index_versions_manifest_checksum",
        ),
        CheckConstraint(
            "artifact_prefix IS NULL OR length(btrim(artifact_prefix)) > 0",
            name="ck_index_versions_artifact_prefix",
        ),
        CheckConstraint(_ACTOR_CHECK, name="ck_index_versions_actor_kind"),
        Index(
            "ix_index_versions_scope_state", "organization_id", "workspace_id", "state"
        ),
        Index(
            "uq_index_versions_one_active",
            "organization_id",
            "workspace_id",
            unique=True,
            postgresql_where=text("state = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    manifest_schema_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    artifact_prefix: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    manifest_checksum_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class KnowledgeIndexDocumentRecord(Base, WorkspaceTenantColumns):
    __tablename__ = "knowledge_index_documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "index_version_id"],
            [
                "knowledge_index_versions.organization_id",
                "knowledge_index_versions.workspace_id",
                "knowledge_index_versions.id",
            ],
            name="fk_index_documents_index_scope",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "document_version_id"],
            [
                "document_versions.organization_id",
                "document_versions.workspace_id",
                "document_versions.id",
            ],
            name="fk_index_documents_document_scope",
            ondelete="RESTRICT",
        ),
    )

    index_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True
    )
    document_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True
    )


class IntegrationRecord(Base, WorkspaceTenantColumns, TimestampColumns, ActorColumns):
    __tablename__ = "integrations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name="fk_integrations_workspace_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "state IN ('active', 'disabled', 'error')",
            name="ck_integrations_state",
        ),
        CheckConstraint(_ACTOR_CHECK, name="ck_integrations_actor_kind"),
        Index(
            "ix_integrations_scope_state", "organization_id", "workspace_id", "state"
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class JobRecord(
    Base, WorkspaceTenantColumns, TimestampColumns, ActorColumns, CorrelationColumns
):
    __tablename__ = "jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name="fk_jobs_workspace_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "organization_id", "workspace_id", "id", name="uq_jobs_scope_id"
        ),
        UniqueConstraint(
            "organization_id",
            "workspace_id",
            "kind",
            "idempotency_key",
            name="uq_jobs_idempotency",
        ),
        CheckConstraint(
            "kind IN ('triage', 'index_build', 'context_collection', 'action_execution')",
            name="ck_jobs_kind",
        ),
        CheckConstraint(
            "state IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_jobs_state",
        ),
        CheckConstraint(
            "payload_version > 0 AND max_attempts > 0 AND attempt_count >= 0 "
            "AND attempt_count <= max_attempts AND state_version > 0 "
            "AND dispatch_generation > 0",
            name="ck_jobs_counters",
        ),
        CheckConstraint(
            "payload_hash ~ '^[0-9a-f]{64}$'",
            name="ck_jobs_payload_hash",
        ),
        CheckConstraint(
            "(last_error_code IS NULL AND last_error_category IS NULL "
            "AND last_error_summary IS NULL AND last_error_retryable IS NULL) OR "
            "(last_error_code IS NOT NULL AND last_error_category IS NOT NULL "
            "AND last_error_summary IS NOT NULL AND last_error_retryable IS NOT NULL)",
            name="ck_jobs_error_shape",
        ),
        CheckConstraint(
            "last_error_category IS NULL OR last_error_category IN "
            "('transient', 'validation', 'authorization', 'configuration', 'internal')",
            name="ck_jobs_error_category",
        ),
        CheckConstraint(
            "last_error_retryable IS NULL OR "
            "last_error_retryable = (last_error_category = 'transient')",
            name="ck_jobs_retryable_category",
        ),
        CheckConstraint(
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
            name="ck_jobs_lifecycle_shape",
        ),
        CheckConstraint(_ACTOR_CHECK, name="ck_jobs_actor_kind"),
        Index(
            "ix_jobs_scope_created",
            "organization_id",
            "workspace_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_jobs_scope_runnable",
            "organization_id",
            "workspace_id",
            "state",
            "available_at",
            "id",
        ),
        Index(
            "ix_jobs_lease_recovery",
            "organization_id",
            "workspace_id",
            "lease_expires_at",
            postgresql_where=text("state = 'running'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(80), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    dispatch_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    claimed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    claim_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_error_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error_summary: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    last_error_retryable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    result_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    result_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    result_metadata: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)


class JobDispatchRecord(Base, WorkspaceTenantColumns):
    __tablename__ = "job_dispatch_outbox"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "job_id"],
            ["jobs.organization_id", "jobs.workspace_id", "jobs.id"],
            name="fk_job_dispatch_outbox_job_scope",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "organization_id",
            "workspace_id",
            "job_id",
            "dispatch_generation",
            name="uq_job_dispatch_outbox_generation",
        ),
        CheckConstraint(
            "dispatch_generation > 0", name="ck_job_dispatch_outbox_generation"
        ),
        CheckConstraint(
            "publish_attempt_count >= 0",
            name="ck_job_dispatch_outbox_publish_attempts",
        ),
        CheckConstraint(
            "(claimed_by IS NULL AND claim_token IS NULL AND claim_expires_at IS NULL) OR "
            "(claimed_by IS NOT NULL AND claim_token IS NOT NULL "
            "AND claim_expires_at IS NOT NULL)",
            name="ck_job_dispatch_outbox_claim_shape",
        ),
        Index(
            "ix_job_dispatch_outbox_unpublished",
            "available_at",
            "created_at",
            postgresql_where=text("published_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    job_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    dispatch_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    claimed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    claim_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    claim_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    publish_attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )


class ActionProposalRecord(
    Base, WorkspaceTenantColumns, TimestampColumns, ActorColumns
):
    __tablename__ = "action_proposals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name="fk_actions_workspace_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "incident_id"],
            ["incidents.organization_id", "incidents.workspace_id", "incidents.id"],
            name="fk_actions_incident_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "triage_run_id"],
            [
                "triage_runs.organization_id",
                "triage_runs.workspace_id",
                "triage_runs.id",
            ],
            name="fk_actions_triage_run_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "organization_id", "workspace_id", "id", name="uq_actions_scope_id"
        ),
        CheckConstraint(
            "risk IN ('informational', 'consequential')",
            name="ck_actions_risk",
        ),
        CheckConstraint(
            "state IN ('proposed', 'awaiting_approval', 'ready', 'executing', "
            "'succeeded', 'failed', 'rejected', 'expired', 'cancelled')",
            name="ck_actions_state",
        ),
        CheckConstraint(_ACTOR_CHECK, name="ck_actions_actor_kind"),
        Index("ix_actions_scope_state", "organization_id", "workspace_id", "state"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    action_type: Mapped[str] = mapped_column(String(120), nullable=False)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    parameters: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    risk: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    incident_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    triage_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    outcome_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class ApprovalRecord(Base, WorkspaceTenantColumns):
    __tablename__ = "approvals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name="fk_approvals_workspace_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "action_id"],
            [
                "action_proposals.organization_id",
                "action_proposals.workspace_id",
                "action_proposals.id",
            ],
            name="fk_approvals_action_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "state IN ('requested', 'approved', 'rejected', 'expired', 'cancelled')",
            name="ck_approvals_state",
        ),
        CheckConstraint(
            "requested_by_kind IN ('human', 'service_account', 'system')",
            name="ck_approvals_requested_actor_kind",
        ),
        CheckConstraint(
            "decided_by_kind IS NULL OR decided_by_kind IN ('human', 'service_account', 'system')",
            name="ck_approvals_decided_actor_kind",
        ),
        Index("ix_approvals_action_state", "action_id", "state"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    action_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_by_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_by_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    requested_by_system_name: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    decided_by_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decided_by_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    decided_by_system_name: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class UsageEventRecord(Base, WorkspaceTenantColumns, CorrelationColumns):
    __tablename__ = "usage_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name="fk_usage_events_workspace_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "organization_id",
            "workspace_id",
            "idempotency_key",
            name="uq_usage_events_idempotency",
        ),
        CheckConstraint("quantity >= 0", name="ck_usage_events_quantity"),
        CheckConstraint(
            "actor_kind IS NULL OR actor_kind IN ('human', 'service_account', 'system')",
            name="ck_usage_events_actor_kind",
        ),
        Index(
            "ix_usage_events_scope_occurred",
            "organization_id",
            "workspace_id",
            "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    actor_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    actor_system_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    retention_policy_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    retain_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AuditEventRecord(Base, CorrelationColumns):
    __tablename__ = "audit_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name="fk_audit_events_workspace_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint(_ACTOR_CHECK, name="ck_audit_events_actor_kind"),
        CheckConstraint(_CLASSIFICATION_CHECK, name="ck_audit_events_classification"),
        Index(
            "ix_audit_events_organization_occurred", "organization_id", "occurred_at"
        ),
        Index(
            "ix_audit_events_workspace_occurred",
            "organization_id",
            "workspace_id",
            "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    workspace_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    actor_system_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    classification: Mapped[str] = mapped_column(String(32), nullable=False)
    retention_policy_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    retain_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    details: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
