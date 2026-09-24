"""Explicit conversions between hosted domain objects and SQLAlchemy records."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, TypeVar
from uuid import UUID

from app.authorization.models import (
    MembershipWorkspaceGrant,
    ServiceAccountGrant,
    ServiceAccountWorkspaceGrant,
)
from app.authorization.permissions import Permission
from app.domain.actions import (
    ActionProposal,
    ActionReference,
    ActionRisk,
    ActionState,
    Approval,
    ApprovalState,
)
from app.domain.common import (
    ActorKind,
    ActorReference,
    CorrelationContext,
    DataClassification,
    OrganizationScope,
    RetentionMarker,
    WorkspaceScope,
)
from app.domain.events import AuditEvent, UsageEvent
from app.domain.identifiers import (
    ActionId,
    ApprovalId,
    AuditEventId,
    CorrelationId,
    DocumentId,
    DocumentVersionId,
    EvidenceId,
    FeedbackId,
    IncidentId,
    IntegrationId,
    JobId,
    KnowledgeIndexVersionId,
    MembershipId,
    MembershipWorkspaceGrantId,
    OrganizationId,
    ServiceAccountGrantId,
    ServiceAccountId,
    ServiceAccountCredentialId,
    ServiceAccountWorkspaceGrantId,
    TriageRunId,
    UsageEventId,
    UserId,
    WorkspaceId,
)
from app.domain.incidents import (
    Evidence,
    Feedback,
    Incident,
    IncidentReference,
    IncidentSource,
    IncidentState,
    TriageRun,
    TriageRunReference,
    TriageRunState,
)
from app.domain.identity import ServiceAccount, ServiceAccountCredential
from app.domain.knowledge import (
    ContentSafetyState,
    Document,
    DocumentCategory,
    DocumentReference,
    DocumentState,
    DocumentVersion,
    DocumentVersionState,
    KnowledgeIndexState,
    KnowledgeIndexVersion,
)
from app.domain.operations import Integration, IntegrationState, Job, JobKind, JobState
from app.domain.tenancy import (
    MembershipRole,
    MembershipState,
    Organization,
    OrganizationMembership,
    OrganizationState,
    User,
    Workspace,
    WorkspaceAccessMode,
    WorkspaceConfiguration,
    WorkspaceState,
)
from app.models.incident import IncidentPayload
from app.models.triage import TriageOutput
from app.persistence.postgres.models import (
    ActionProposalRecord,
    ApprovalRecord,
    AuditEventRecord,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceRecord,
    FeedbackRecord,
    IncidentRecord,
    IntegrationRecord,
    JobRecord,
    KnowledgeIndexDocumentRecord,
    KnowledgeIndexVersionRecord,
    MembershipWorkspaceGrantRecord,
    OrganizationMembershipRecord,
    OrganizationRecord,
    ServiceAccountAuthorizationGrantRecord,
    ServiceAccountCredentialRecord,
    ServiceAccountRecord,
    ServiceAccountWorkspaceGrantRecord,
    TriageRunRecord,
    UsageEventRecord,
    UserRecord,
    WorkspaceRecord,
    WorkspaceConfigurationRecord,
)

IdT = TypeVar("IdT")


def _uuid(value: object) -> UUID:
    return UUID(str(value))


def _identifier(identifier_type: type[IdT], value: UUID) -> IdT:
    return identifier_type(str(value))  # type: ignore[call-arg]


def _scope(organization_id: UUID, workspace_id: UUID) -> WorkspaceScope:
    return WorkspaceScope(
        _identifier(OrganizationId, organization_id),
        _identifier(WorkspaceId, workspace_id),
    )


def _actor_columns(actor: ActorReference) -> dict[str, Any]:
    return {
        "actor_kind": actor.kind.value,
        "actor_id": _uuid(actor.actor_id) if actor.actor_id else None,
        "actor_system_name": actor.system_name,
    }


def _actor(kind: str, actor_id: UUID | None, system_name: str | None) -> ActorReference:
    actor_kind = ActorKind(kind)
    typed_id: UserId | ServiceAccountId | None
    if actor_kind is ActorKind.HUMAN:
        typed_id = _identifier(UserId, actor_id) if actor_id else None
    elif actor_kind is ActorKind.SERVICE_ACCOUNT:
        typed_id = _identifier(ServiceAccountId, actor_id) if actor_id else None
    else:
        typed_id = None
    return ActorReference(actor_kind, actor_id=typed_id, system_name=system_name)


def _retention_columns(
    classification: DataClassification,
    retention: RetentionMarker,
) -> dict[str, Any]:
    return {
        "classification": classification.value,
        "retention_policy_ref": retention.policy_ref,
        "retain_until": retention.retain_until,
    }


def _retention(
    classification: str,
    policy_ref: str | None,
    retain_until,
) -> tuple[DataClassification, RetentionMarker]:
    return DataClassification(classification), RetentionMarker(policy_ref, retain_until)


def _correlation_columns(correlation: CorrelationContext) -> dict[str, Any]:
    return {
        "correlation_id": _uuid(correlation.correlation_id),
        "correlation_incident_id": _uuid(correlation.incident_id)
        if correlation.incident_id
        else None,
        "correlation_triage_run_id": _uuid(correlation.triage_run_id)
        if correlation.triage_run_id
        else None,
        "correlation_job_id": _uuid(correlation.job_id) if correlation.job_id else None,
    }


def _correlation(record: Any) -> CorrelationContext:
    return CorrelationContext(
        _identifier(CorrelationId, record.correlation_id),
        incident_id=(
            _identifier(IncidentId, record.correlation_incident_id)
            if record.correlation_incident_id
            else None
        ),
        triage_run_id=(
            _identifier(TriageRunId, record.correlation_triage_run_id)
            if record.correlation_triage_run_id
            else None
        ),
        job_id=(
            _identifier(JobId, record.correlation_job_id)
            if record.correlation_job_id
            else None
        ),
    )


def user_to_record(user: User) -> UserRecord:
    return UserRecord(
        id=_uuid(user.id),
        email=user.email,
        display_name=user.display_name,
        identity_provider=user.identity_provider,
        provider_subject=user.provider_subject,
        created_at=user.created_at,
        disabled_at=user.disabled_at,
    )


def user_from_record(record: UserRecord) -> User:
    return User(
        id=_identifier(UserId, record.id),
        email=record.email,
        display_name=record.display_name,
        identity_provider=record.identity_provider,
        provider_subject=record.provider_subject,
        created_at=record.created_at,
        disabled_at=record.disabled_at,
    )


def service_account_to_record(account: ServiceAccount) -> ServiceAccountRecord:
    disabled_by = (
        _actor_columns(account.disabled_by) if account.disabled_by is not None else None
    )
    return ServiceAccountRecord(
        id=_uuid(account.id),
        name=account.name,
        created_at=account.created_at,
        updated_at=account.updated_at,
        disabled_at=account.disabled_at,
        disabled_by_kind=(disabled_by["actor_kind"] if disabled_by else None),
        disabled_by_id=(disabled_by["actor_id"] if disabled_by else None),
        disabled_by_system_name=(
            disabled_by["actor_system_name"] if disabled_by else None
        ),
        **_actor_columns(account.created_by),
    )


def service_account_from_record(record: ServiceAccountRecord) -> ServiceAccount:
    return ServiceAccount(
        id=_identifier(ServiceAccountId, record.id),
        name=record.name,
        created_by=_actor(record.actor_kind, record.actor_id, record.actor_system_name),
        created_at=record.created_at,
        updated_at=record.updated_at,
        disabled_at=record.disabled_at,
        disabled_by=(
            _actor(
                record.disabled_by_kind,
                record.disabled_by_id,
                record.disabled_by_system_name,
            )
            if record.disabled_by_kind
            else None
        ),
    )


def service_account_credential_to_record(
    credential: ServiceAccountCredential,
) -> ServiceAccountCredentialRecord:
    created_by = _actor_columns(credential.created_by)
    revoked_by = (
        _actor_columns(credential.revoked_by)
        if credential.revoked_by is not None
        else None
    )
    return ServiceAccountCredentialRecord(
        id=_uuid(credential.id),
        service_account_id=_uuid(credential.service_account_id),
        lookup_id=credential.lookup_id,
        verifier=credential.verifier,
        salt=credential.salt,
        algorithm=credential.algorithm,
        created_by_kind=created_by["actor_kind"],
        created_by_id=created_by["actor_id"],
        created_by_system_name=created_by["actor_system_name"],
        created_at=credential.created_at,
        expires_at=credential.expires_at,
        revoked_at=credential.revoked_at,
        revoked_by_kind=(revoked_by["actor_kind"] if revoked_by else None),
        revoked_by_id=(revoked_by["actor_id"] if revoked_by else None),
        revoked_by_system_name=(
            revoked_by["actor_system_name"] if revoked_by else None
        ),
        last_used_at=credential.last_used_at,
    )


def service_account_credential_from_record(
    record: ServiceAccountCredentialRecord,
) -> ServiceAccountCredential:
    return ServiceAccountCredential(
        id=_identifier(ServiceAccountCredentialId, record.id),
        service_account_id=_identifier(ServiceAccountId, record.service_account_id),
        lookup_id=record.lookup_id,
        verifier=record.verifier,
        salt=record.salt,
        algorithm=record.algorithm,
        created_by=_actor(
            record.created_by_kind,
            record.created_by_id,
            record.created_by_system_name,
        ),
        created_at=record.created_at,
        expires_at=record.expires_at,
        revoked_at=record.revoked_at,
        revoked_by=(
            _actor(
                record.revoked_by_kind,
                record.revoked_by_id,
                record.revoked_by_system_name,
            )
            if record.revoked_by_kind
            else None
        ),
        last_used_at=record.last_used_at,
    )


def organization_to_record(organization: Organization) -> OrganizationRecord:
    return OrganizationRecord(
        id=_uuid(organization.id),
        name=organization.name,
        slug=organization.slug,
        state=organization.state.value,
        created_at=organization.created_at,
        updated_at=organization.updated_at,
        **_actor_columns(organization.created_by),
    )


def organization_from_record(record: OrganizationRecord) -> Organization:
    return Organization(
        id=_identifier(OrganizationId, record.id),
        name=record.name,
        slug=record.slug,
        state=OrganizationState(record.state),
        created_by=_actor(record.actor_kind, record.actor_id, record.actor_system_name),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def membership_to_record(
    membership: OrganizationMembership,
) -> OrganizationMembershipRecord:
    return OrganizationMembershipRecord(
        id=_uuid(membership.id),
        organization_id=_uuid(membership.organization_id),
        user_id=_uuid(membership.user_id),
        role=membership.role.value,
        state=membership.state.value,
        workspace_access=membership.workspace_access.value,
        created_at=membership.created_at,
        updated_at=membership.updated_at,
        **_actor_columns(membership.created_by),
    )


def membership_from_record(
    record: OrganizationMembershipRecord,
) -> OrganizationMembership:
    return OrganizationMembership(
        id=_identifier(MembershipId, record.id),
        organization_id=_identifier(OrganizationId, record.organization_id),
        user_id=_identifier(UserId, record.user_id),
        role=MembershipRole(record.role),
        state=MembershipState(record.state),
        workspace_access=WorkspaceAccessMode(record.workspace_access),
        created_by=_actor(record.actor_kind, record.actor_id, record.actor_system_name),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def membership_workspace_grant_to_record(
    grant: MembershipWorkspaceGrant,
) -> MembershipWorkspaceGrantRecord:
    return MembershipWorkspaceGrantRecord(
        id=_uuid(grant.id),
        organization_id=_uuid(grant.scope.organization_id),
        membership_id=_uuid(grant.membership_id),
        workspace_id=_uuid(grant.scope.workspace_id),
        created_at=grant.created_at,
        **_actor_columns(grant.created_by),
    )


def membership_workspace_grant_from_record(
    record: MembershipWorkspaceGrantRecord,
) -> MembershipWorkspaceGrant:
    return MembershipWorkspaceGrant(
        id=_identifier(MembershipWorkspaceGrantId, record.id),
        organization_id=_identifier(OrganizationId, record.organization_id),
        membership_id=_identifier(MembershipId, record.membership_id),
        workspace_id=_identifier(WorkspaceId, record.workspace_id),
        created_by=_actor(record.actor_kind, record.actor_id, record.actor_system_name),
        created_at=record.created_at,
    )


def service_account_grant_to_record(
    grant: ServiceAccountGrant,
) -> ServiceAccountAuthorizationGrantRecord:
    revoked_by = (
        _actor_columns(grant.revoked_by) if grant.revoked_by is not None else None
    )
    return ServiceAccountAuthorizationGrantRecord(
        id=_uuid(grant.id),
        organization_id=_uuid(grant.organization_id),
        service_account_id=_uuid(grant.service_account_id),
        permissions=sorted(permission.value for permission in grant.permissions),
        workspace_access=grant.workspace_access.value,
        created_at=grant.created_at,
        updated_at=grant.updated_at,
        revoked_at=grant.revoked_at,
        revoked_by_kind=(revoked_by["actor_kind"] if revoked_by else None),
        revoked_by_id=(revoked_by["actor_id"] if revoked_by else None),
        revoked_by_system_name=(
            revoked_by["actor_system_name"] if revoked_by else None
        ),
        **_actor_columns(grant.created_by),
    )


def service_account_grant_from_record(
    record: ServiceAccountAuthorizationGrantRecord,
) -> ServiceAccountGrant:
    return ServiceAccountGrant(
        id=_identifier(ServiceAccountGrantId, record.id),
        organization_id=_identifier(OrganizationId, record.organization_id),
        service_account_id=_identifier(ServiceAccountId, record.service_account_id),
        permissions=frozenset(Permission(value) for value in record.permissions),
        workspace_access=WorkspaceAccessMode(record.workspace_access),
        created_by=_actor(record.actor_kind, record.actor_id, record.actor_system_name),
        created_at=record.created_at,
        updated_at=record.updated_at,
        revoked_at=record.revoked_at,
        revoked_by=(
            _actor(
                record.revoked_by_kind,
                record.revoked_by_id,
                record.revoked_by_system_name,
            )
            if record.revoked_by_kind
            else None
        ),
    )


def service_account_workspace_grant_to_record(
    grant: ServiceAccountWorkspaceGrant,
) -> ServiceAccountWorkspaceGrantRecord:
    return ServiceAccountWorkspaceGrantRecord(
        id=_uuid(grant.id),
        organization_id=_uuid(grant.scope.organization_id),
        service_account_grant_id=_uuid(grant.service_account_grant_id),
        workspace_id=_uuid(grant.scope.workspace_id),
        created_at=grant.created_at,
        **_actor_columns(grant.created_by),
    )


def service_account_workspace_grant_from_record(
    record: ServiceAccountWorkspaceGrantRecord,
) -> ServiceAccountWorkspaceGrant:
    return ServiceAccountWorkspaceGrant(
        id=_identifier(ServiceAccountWorkspaceGrantId, record.id),
        organization_id=_identifier(OrganizationId, record.organization_id),
        service_account_grant_id=_identifier(ServiceAccountGrantId, record.service_account_grant_id),
        workspace_id=_identifier(WorkspaceId, record.workspace_id),
        created_by=_actor(record.actor_kind, record.actor_id, record.actor_system_name),
        created_at=record.created_at,
    )


def workspace_to_record(workspace: Workspace) -> WorkspaceRecord:
    return WorkspaceRecord(
        id=_uuid(workspace.id),
        organization_id=_uuid(workspace.organization_id),
        name=workspace.name,
        slug=workspace.slug,
        state=workspace.state.value,
        description=workspace.description,
        version=workspace.version,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
        **_actor_columns(workspace.created_by),
    )


def workspace_from_record(record: WorkspaceRecord) -> Workspace:
    return Workspace(
        id=_identifier(WorkspaceId, record.id),
        organization_id=_identifier(OrganizationId, record.organization_id),
        name=record.name,
        slug=record.slug,
        state=WorkspaceState(record.state),
        description=record.description,
        version=record.version,
        created_by=_actor(record.actor_kind, record.actor_id, record.actor_system_name),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def workspace_configuration_to_record(
    configuration: WorkspaceConfiguration,
) -> WorkspaceConfigurationRecord:
    updated_by = _actor_columns(configuration.updated_by)
    return WorkspaceConfigurationRecord(
        organization_id=_uuid(configuration.scope.organization_id),
        workspace_id=_uuid(configuration.scope.workspace_id),
        schema_version=configuration.schema_version,
        version=configuration.version,
        rag_top_k=configuration.rag_top_k,
        llm_temperature=configuration.llm_temperature,
        updated_by_kind=updated_by["actor_kind"],
        updated_by_id=updated_by["actor_id"],
        updated_by_system_name=updated_by["actor_system_name"],
        created_at=configuration.created_at,
        updated_at=configuration.updated_at,
    )


def workspace_configuration_from_record(
    record: WorkspaceConfigurationRecord,
) -> WorkspaceConfiguration:
    return WorkspaceConfiguration(
        scope=_scope(record.organization_id, record.workspace_id),
        schema_version=record.schema_version,
        version=record.version,
        rag_top_k=record.rag_top_k,
        llm_temperature=record.llm_temperature,
        updated_by=_actor(
            record.updated_by_kind,
            record.updated_by_id,
            record.updated_by_system_name,
        ),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def incident_to_record(incident: Incident) -> IncidentRecord:
    return IncidentRecord(
        id=_uuid(incident.id),
        organization_id=_uuid(incident.scope.organization_id),
        workspace_id=_uuid(incident.scope.workspace_id),
        payload=incident.to_legacy_payload(),
        source_provider=incident.source.provider,
        source_type=incident.source.source_type,
        source_received_at=incident.source.received_at,
        source_external_id=incident.source.external_id,
        source_url=incident.source.source_url,
        state=incident.state.value,
        created_at=incident.created_at,
        updated_at=incident.updated_at,
        **_actor_columns(incident.created_by),
        **_retention_columns(incident.classification, incident.retention),
        **_correlation_columns(incident.correlation),
    )


def incident_from_record(record: IncidentRecord) -> Incident:
    classification, retention = _retention(
        record.classification,
        record.retention_policy_ref,
        record.retain_until,
    )
    return Incident(
        id=_identifier(IncidentId, record.id),
        scope=_scope(record.organization_id, record.workspace_id),
        payload=IncidentPayload.model_validate(record.payload),
        source=IncidentSource(
            provider=record.source_provider,
            source_type=record.source_type,
            received_at=record.source_received_at,
            external_id=record.source_external_id,
            source_url=record.source_url,
        ),
        state=IncidentState(record.state),
        created_by=_actor(record.actor_kind, record.actor_id, record.actor_system_name),
        created_at=record.created_at,
        updated_at=record.updated_at,
        correlation=_correlation(record),
        classification=classification,
        retention=retention,
    )


def triage_run_to_record(run: TriageRun) -> TriageRunRecord:
    return TriageRunRecord(
        id=_uuid(run.id),
        organization_id=_uuid(run.scope.organization_id),
        workspace_id=_uuid(run.scope.workspace_id),
        incident_id=_uuid(run.incident.id),
        state=run.state.value,
        created_at=run.created_at,
        updated_at=run.updated_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        result=run.result.model_dump(mode="json") if run.result else None,
        error_message=run.error_message,
        **_actor_columns(run.created_by),
        **_retention_columns(run.classification, run.retention),
        **_correlation_columns(run.correlation),
    )


def triage_run_from_record(record: TriageRunRecord) -> TriageRun:
    scope = _scope(record.organization_id, record.workspace_id)
    classification, retention = _retention(
        record.classification,
        record.retention_policy_ref,
        record.retain_until,
    )
    return TriageRun(
        id=_identifier(TriageRunId, record.id),
        scope=scope,
        incident=IncidentReference(_identifier(IncidentId, record.incident_id), scope),
        state=TriageRunState(record.state),
        created_by=_actor(record.actor_kind, record.actor_id, record.actor_system_name),
        created_at=record.created_at,
        updated_at=record.updated_at,
        correlation=_correlation(record),
        started_at=record.started_at,
        completed_at=record.completed_at,
        result=TriageOutput.model_validate(record.result) if record.result else None,
        error_message=record.error_message,
        classification=classification,
        retention=retention,
    )


def evidence_to_record(evidence: Evidence) -> EvidenceRecord:
    return EvidenceRecord(
        id=_uuid(evidence.id),
        organization_id=_uuid(evidence.scope.organization_id),
        workspace_id=_uuid(evidence.scope.workspace_id),
        triage_run_id=_uuid(evidence.triage_run.id),
        type=evidence.type,
        source=evidence.source,
        reason=evidence.reason,
        created_at=evidence.created_at,
        **_retention_columns(evidence.classification, evidence.retention),
    )


def evidence_from_record(record: EvidenceRecord) -> Evidence:
    scope = _scope(record.organization_id, record.workspace_id)
    classification, retention = _retention(
        record.classification,
        record.retention_policy_ref,
        record.retain_until,
    )
    return Evidence(
        id=_identifier(EvidenceId, record.id),
        scope=scope,
        triage_run=TriageRunReference(
            _identifier(TriageRunId, record.triage_run_id), scope
        ),
        type=record.type,  # type: ignore[arg-type]
        source=record.source,
        reason=record.reason,
        created_at=record.created_at,
        classification=classification,
        retention=retention,
    )


def feedback_to_record(feedback: Feedback) -> FeedbackRecord:
    actor = _actor_columns(feedback.submitted_by)
    return FeedbackRecord(
        id=_uuid(feedback.id),
        organization_id=_uuid(feedback.scope.organization_id),
        workspace_id=_uuid(feedback.scope.workspace_id),
        triage_run_id=_uuid(feedback.triage_run.id),
        submitted_by_kind=actor["actor_kind"],
        submitted_by_id=actor["actor_id"],
        submitted_by_system_name=actor["actor_system_name"],
        created_at=feedback.created_at,
        diagnosis_correct=feedback.diagnosis_correct,
        actions_useful=feedback.actions_useful,
        notes=feedback.notes,
        **_retention_columns(feedback.classification, feedback.retention),
    )


def feedback_from_record(record: FeedbackRecord) -> Feedback:
    scope = _scope(record.organization_id, record.workspace_id)
    classification, retention = _retention(
        record.classification,
        record.retention_policy_ref,
        record.retain_until,
    )
    return Feedback(
        id=_identifier(FeedbackId, record.id),
        scope=scope,
        triage_run=TriageRunReference(
            _identifier(TriageRunId, record.triage_run_id), scope
        ),
        submitted_by=_actor(
            record.submitted_by_kind,
            record.submitted_by_id,
            record.submitted_by_system_name,
        ),
        created_at=record.created_at,
        diagnosis_correct=record.diagnosis_correct,
        actions_useful=record.actions_useful,
        notes=record.notes,
        classification=classification,
        retention=retention,
    )


def document_to_record(document: Document) -> DocumentRecord:
    return DocumentRecord(
        id=_uuid(document.id),
        organization_id=_uuid(document.scope.organization_id),
        workspace_id=_uuid(document.scope.workspace_id),
        name=document.name,
        category=document.category.value,
        state=document.state.value,
        failure_reason=document.failure_reason,
        created_at=document.created_at,
        updated_at=document.updated_at,
        **_actor_columns(document.created_by),
        **_retention_columns(document.classification, document.retention),
    )


def document_from_record(record: DocumentRecord) -> Document:
    classification, retention = _retention(
        record.classification,
        record.retention_policy_ref,
        record.retain_until,
    )
    return Document(
        id=_identifier(DocumentId, record.id),
        scope=_scope(record.organization_id, record.workspace_id),
        name=record.name,
        category=DocumentCategory(record.category),
        state=DocumentState(record.state),
        created_by=_actor(record.actor_kind, record.actor_id, record.actor_system_name),
        created_at=record.created_at,
        updated_at=record.updated_at,
        classification=classification,
        retention=retention,
        failure_reason=record.failure_reason,
    )


def document_version_to_record(version: DocumentVersion) -> DocumentVersionRecord:
    return DocumentVersionRecord(
        id=_uuid(version.id),
        organization_id=_uuid(version.scope.organization_id),
        workspace_id=_uuid(version.scope.workspace_id),
        document_id=_uuid(version.document.id),
        version_number=version.version_number,
        checksum_sha256=version.checksum_sha256,
        size_bytes=version.size_bytes,
        media_type=version.media_type,
        original_filename=version.original_filename,
        storage_provider=version.storage_provider,
        object_key=version.object_key,
        state=version.state.value,
        content_safety_state=version.content_safety_state.value,
        verified_checksum_sha256=version.verified_checksum_sha256,
        verified_size_bytes=version.verified_size_bytes,
        verified_media_type=version.verified_media_type,
        created_at=version.created_at,
        updated_at=version.updated_at,
        finalized_at=version.finalized_at,
        failure_reason=version.failure_reason,
        object_deleted_at=version.object_deleted_at,
        **_actor_columns(version.created_by),
    )


def document_version_from_record(record: DocumentVersionRecord) -> DocumentVersion:
    scope = _scope(record.organization_id, record.workspace_id)
    return DocumentVersion(
        id=_identifier(DocumentVersionId, record.id),
        scope=scope,
        document=DocumentReference(_identifier(DocumentId, record.document_id), scope),
        version_number=record.version_number,
        checksum_sha256=record.checksum_sha256,
        size_bytes=record.size_bytes,
        media_type=record.media_type,
        original_filename=record.original_filename,
        storage_provider=record.storage_provider,
        object_key=record.object_key,
        state=DocumentVersionState(record.state),
        content_safety_state=ContentSafetyState(record.content_safety_state),
        verified_checksum_sha256=record.verified_checksum_sha256,
        verified_size_bytes=record.verified_size_bytes,
        verified_media_type=record.verified_media_type,
        created_by=_actor(record.actor_kind, record.actor_id, record.actor_system_name),
        created_at=record.created_at,
        updated_at=record.updated_at,
        finalized_at=record.finalized_at,
        failure_reason=record.failure_reason,
        object_deleted_at=record.object_deleted_at,
    )


def knowledge_index_to_record(
    index: KnowledgeIndexVersion,
) -> KnowledgeIndexVersionRecord:
    return KnowledgeIndexVersionRecord(
        id=_uuid(index.id),
        organization_id=_uuid(index.scope.organization_id),
        workspace_id=_uuid(index.scope.workspace_id),
        state=index.state.value,
        created_at=index.created_at,
        updated_at=index.updated_at,
        activated_at=index.activated_at,
        published_at=index.published_at,
        superseded_at=index.superseded_at,
        manifest_schema_version=index.manifest_schema_version,
        artifact_prefix=index.artifact_prefix,
        manifest_checksum_sha256=index.manifest_checksum_sha256,
        failure_reason=index.failure_reason,
        **_actor_columns(index.created_by),
    )


def knowledge_index_document_records(
    index: KnowledgeIndexVersion,
) -> list[KnowledgeIndexDocumentRecord]:
    return [
        KnowledgeIndexDocumentRecord(
            organization_id=_uuid(index.scope.organization_id),
            workspace_id=_uuid(index.scope.workspace_id),
            index_version_id=_uuid(index.id),
            document_version_id=_uuid(document_version_id),
        )
        for document_version_id in index.source_document_versions
    ]


def knowledge_index_from_record(
    record: KnowledgeIndexVersionRecord,
    source_document_versions: Iterable[UUID],
) -> KnowledgeIndexVersion:
    return KnowledgeIndexVersion(
        id=_identifier(KnowledgeIndexVersionId, record.id),
        scope=_scope(record.organization_id, record.workspace_id),
        state=KnowledgeIndexState(record.state),
        source_document_versions=tuple(
            _identifier(DocumentVersionId, value) for value in source_document_versions
        ),
        created_by=_actor(record.actor_kind, record.actor_id, record.actor_system_name),
        created_at=record.created_at,
        updated_at=record.updated_at,
        activated_at=record.activated_at,
        published_at=record.published_at,
        superseded_at=record.superseded_at,
        manifest_schema_version=record.manifest_schema_version,
        artifact_prefix=record.artifact_prefix,
        manifest_checksum_sha256=record.manifest_checksum_sha256,
        failure_reason=record.failure_reason,
    )


def integration_to_record(integration: Integration) -> IntegrationRecord:
    return IntegrationRecord(
        id=_uuid(integration.id),
        organization_id=_uuid(integration.scope.organization_id),
        workspace_id=_uuid(integration.scope.workspace_id),
        provider=integration.provider,
        name=integration.name,
        state=integration.state.value,
        last_error=integration.last_error,
        created_at=integration.created_at,
        updated_at=integration.updated_at,
        **_actor_columns(integration.created_by),
    )


def integration_from_record(record: IntegrationRecord) -> Integration:
    return Integration(
        id=_identifier(IntegrationId, record.id),
        scope=_scope(record.organization_id, record.workspace_id),
        provider=record.provider,
        name=record.name,
        state=IntegrationState(record.state),
        created_by=_actor(record.actor_kind, record.actor_id, record.actor_system_name),
        created_at=record.created_at,
        updated_at=record.updated_at,
        last_error=record.last_error,
    )


def job_to_record(job: Job) -> JobRecord:
    return JobRecord(
        id=_uuid(job.id),
        organization_id=_uuid(job.scope.organization_id),
        workspace_id=_uuid(job.scope.workspace_id),
        kind=job.kind.value,
        subject_type=job.subject_type,
        subject_id=job.subject_id,
        state=job.state.value,
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error_message=job.error_message,
        **_actor_columns(job.created_by),
        **_correlation_columns(job.correlation),
    )


def job_from_record(record: JobRecord) -> Job:
    return Job(
        id=_identifier(JobId, record.id),
        scope=_scope(record.organization_id, record.workspace_id),
        kind=JobKind(record.kind),
        subject_type=record.subject_type,
        subject_id=record.subject_id,
        state=JobState(record.state),
        created_by=_actor(record.actor_kind, record.actor_id, record.actor_system_name),
        created_at=record.created_at,
        updated_at=record.updated_at,
        correlation=_correlation(record),
        started_at=record.started_at,
        completed_at=record.completed_at,
        error_message=record.error_message,
    )


def action_to_record(action: ActionProposal) -> ActionProposalRecord:
    return ActionProposalRecord(
        id=_uuid(action.id),
        organization_id=_uuid(action.scope.organization_id),
        workspace_id=_uuid(action.scope.workspace_id),
        action_type=action.action_type,
        target=action.target,
        parameters=dict(action.parameters),
        risk=action.risk.value,
        state=action.state.value,
        incident_id=_uuid(action.incident.id) if action.incident else None,
        triage_run_id=_uuid(action.triage_run.id) if action.triage_run else None,
        completed_at=action.completed_at,
        outcome_reference=action.outcome_reference,
        error_message=action.error_message,
        created_at=action.created_at,
        updated_at=action.updated_at,
        **_actor_columns(action.proposed_by),
    )


def action_from_record(record: ActionProposalRecord) -> ActionProposal:
    scope = _scope(record.organization_id, record.workspace_id)
    return ActionProposal(
        id=_identifier(ActionId, record.id),
        scope=scope,
        action_type=record.action_type,
        target=record.target,
        parameters=tuple(record.parameters.items()),
        risk=ActionRisk(record.risk),
        state=ActionState(record.state),
        proposed_by=_actor(
            record.actor_kind, record.actor_id, record.actor_system_name
        ),
        created_at=record.created_at,
        updated_at=record.updated_at,
        incident=(
            IncidentReference(_identifier(IncidentId, record.incident_id), scope)
            if record.incident_id
            else None
        ),
        triage_run=(
            TriageRunReference(_identifier(TriageRunId, record.triage_run_id), scope)
            if record.triage_run_id
            else None
        ),
        completed_at=record.completed_at,
        outcome_reference=record.outcome_reference,
        error_message=record.error_message,
    )


def approval_to_record(approval: Approval) -> ApprovalRecord:
    requested = _actor_columns(approval.requested_by)
    decided = _actor_columns(approval.decided_by) if approval.decided_by else None
    return ApprovalRecord(
        id=_uuid(approval.id),
        organization_id=_uuid(approval.scope.organization_id),
        workspace_id=_uuid(approval.scope.workspace_id),
        action_id=_uuid(approval.action.id),
        state=approval.state.value,
        requested_by_kind=requested["actor_kind"],
        requested_by_id=requested["actor_id"],
        requested_by_system_name=requested["actor_system_name"],
        created_at=approval.created_at,
        updated_at=approval.updated_at,
        expires_at=approval.expires_at,
        decided_by_kind=decided["actor_kind"] if decided else None,
        decided_by_id=decided["actor_id"] if decided else None,
        decided_by_system_name=decided["actor_system_name"] if decided else None,
        decided_at=approval.decided_at,
        reason=approval.reason,
    )


def approval_from_record(record: ApprovalRecord) -> Approval:
    scope = _scope(record.organization_id, record.workspace_id)
    decided_by = (
        _actor(
            record.decided_by_kind, record.decided_by_id, record.decided_by_system_name
        )
        if record.decided_by_kind
        else None
    )
    return Approval(
        id=_identifier(ApprovalId, record.id),
        scope=scope,
        action=ActionReference(_identifier(ActionId, record.action_id), scope),
        state=ApprovalState(record.state),
        requested_by=_actor(
            record.requested_by_kind,
            record.requested_by_id,
            record.requested_by_system_name,
        ),
        created_at=record.created_at,
        updated_at=record.updated_at,
        expires_at=record.expires_at,
        decided_by=decided_by,
        decided_at=record.decided_at,
        reason=record.reason,
    )


def usage_event_to_record(event: UsageEvent) -> UsageEventRecord:
    actor = _actor_columns(event.actor) if event.actor else None
    return UsageEventRecord(
        id=_uuid(event.id),
        organization_id=_uuid(event.scope.organization_id),
        workspace_id=_uuid(event.scope.workspace_id),
        category=event.category,
        quantity=event.quantity,
        unit=event.unit,
        occurred_at=event.occurred_at,
        actor_kind=actor["actor_kind"] if actor else None,
        actor_id=actor["actor_id"] if actor else None,
        actor_system_name=actor["actor_system_name"] if actor else None,
        idempotency_key=event.idempotency_key,
        retention_policy_ref=event.retention.policy_ref,
        retain_until=event.retention.retain_until,
        **_correlation_columns(event.correlation),
    )


def usage_event_from_record(record: UsageEventRecord) -> UsageEvent:
    actor = (
        _actor(record.actor_kind, record.actor_id, record.actor_system_name)
        if record.actor_kind
        else None
    )
    return UsageEvent(
        id=_identifier(UsageEventId, record.id),
        scope=_scope(record.organization_id, record.workspace_id),
        category=record.category,
        quantity=record.quantity,
        unit=record.unit,
        occurred_at=record.occurred_at,
        correlation=_correlation(record),
        actor=actor,
        idempotency_key=record.idempotency_key,
        retention=RetentionMarker(record.retention_policy_ref, record.retain_until),
    )


def audit_event_to_record(event: AuditEvent) -> AuditEventRecord:
    return AuditEventRecord(
        id=_uuid(event.id),
        organization_id=_uuid(event.organization_scope.organization_id),
        workspace_id=(
            _uuid(event.workspace_scope.workspace_id) if event.workspace_scope else None
        ),
        event_type=event.event_type,
        target_type=event.target_type,
        target_id=event.target_id,
        occurred_at=event.occurred_at,
        classification=event.classification.value,
        retention_policy_ref=event.retention.policy_ref,
        retain_until=event.retention.retain_until,
        details=dict(event.details),
        **_actor_columns(event.actor),
        **_correlation_columns(event.correlation),
    )


def audit_event_from_record(record: AuditEventRecord) -> AuditEvent:
    organization_id = _identifier(OrganizationId, record.organization_id)
    workspace_scope = (
        WorkspaceScope(organization_id, _identifier(WorkspaceId, record.workspace_id))
        if record.workspace_id
        else None
    )
    return AuditEvent(
        id=_identifier(AuditEventId, record.id),
        organization_scope=OrganizationScope(organization_id),
        workspace_scope=workspace_scope,
        event_type=record.event_type,
        target_type=record.target_type,
        target_id=record.target_id,
        actor=_actor(record.actor_kind, record.actor_id, record.actor_system_name),
        occurred_at=record.occurred_at,
        correlation=_correlation(record),
        classification=DataClassification(record.classification),
        retention=RetentionMarker(record.retention_policy_ref, record.retain_until),
        details=tuple(record.details.items()),
    )
