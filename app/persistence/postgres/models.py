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
    identity_provider: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    disabled_at: Mapped[datetime | None] = mapped_column(
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
        CheckConstraint(
            "role IN ('owner', 'admin', 'operator', 'viewer')",
            name="ck_memberships_role",
        ),
        CheckConstraint(
            "state IN ('invited', 'active', 'suspended', 'revoked')",
            name="ck_memberships_state",
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
        CheckConstraint(
            "state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_triage_runs_state",
        ),
        CheckConstraint(_ACTOR_CHECK, name="ck_triage_runs_actor_kind"),
        CheckConstraint(_CLASSIFICATION_CHECK, name="ck_triage_runs_classification"),
        Index("ix_triage_runs_incident_created", "incident_id", "created_at"),
        Index("ix_triage_runs_scope_state", "organization_id", "workspace_id", "state"),
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
        Index("ix_evidence_triage_run", "triage_run_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    triage_run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
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
        CheckConstraint(_ACTOR_CHECK, name="ck_document_versions_actor_kind"),
        Index("ix_document_versions_document", "document_id", "version_number"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
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
            "state IN ('building', 'active', 'failed', 'inactive')",
            name="ck_index_versions_state",
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
        CheckConstraint(
            "kind IN ('triage', 'index_build', 'context_collection', 'action_execution')",
            name="ck_jobs_kind",
        ),
        CheckConstraint(
            "state IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_jobs_state",
        ),
        CheckConstraint(_ACTOR_CHECK, name="ck_jobs_actor_kind"),
        Index(
            "ix_jobs_scope_state_created",
            "organization_id",
            "workspace_id",
            "state",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(80), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


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
