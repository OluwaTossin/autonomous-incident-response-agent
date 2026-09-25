"""Domain/record mapping coverage without requiring a database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.actions import (
    AcknowledgeIncidentParameters,
    ActionPolicyReason,
    ActionPolicyStatus,
    ActionProposal,
    ActionProposalState,
    ActionProposalType,
    ActionReversibility,
    ActionRiskLevel,
    ActionTarget,
    ActionTargetProvenance,
    ActionTargetType,
    Approval,
    ApprovalState,
)
from app.domain.common import (
    ActorKind,
    ActorReference,
    CorrelationContext,
    OrganizationScope,
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
    OrganizationId,
    ServiceAccountCredentialId,
    ServiceAccountId,
    TriageRunId,
    UsageEventId,
    UserId,
    WorkspaceId,
)
from app.domain.identity import ServiceAccount, ServiceAccountCredential
from app.domain.incidents import (
    Evidence,
    Feedback,
    Incident,
    IncidentSource,
    IncidentState,
    TriageRun,
    TriageRunState,
)
from app.domain.knowledge import (
    Document,
    DocumentCategory,
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
    User,
    Workspace,
)
from app.models.incident import IncidentPayload
from app.persistence.postgres import mappers

NOW = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)


def _id(identifier_type, suffix: int):
    return identifier_type(f"00000000-0000-4000-8000-{suffix:012d}")


ACTOR = ActorReference(ActorKind.HUMAN, actor_id=_id(UserId, 1))
SCOPE = WorkspaceScope(_id(OrganizationId, 2), _id(WorkspaceId, 3))
INCIDENT_ID = _id(IncidentId, 4)
TRIAGE_ID = _id(TriageRunId, 5)
CORRELATION = CorrelationContext(
    _id(CorrelationId, 6),
    incident_id=INCIDENT_ID,
    triage_run_id=TRIAGE_ID,
)


USER = User(
    id=_id(UserId, 1),
    email="operator@example.com",
    display_name="Operator",
    identity_provider="managed-idp",
    provider_subject="subject-1",
    created_at=NOW,
)
SERVICE_ACCOUNT = ServiceAccount(
    id=_id(ServiceAccountId, 20),
    name="CI integration",
    created_by=ACTOR,
    created_at=NOW,
    updated_at=NOW,
)
SERVICE_CREDENTIAL = ServiceAccountCredential(
    id=_id(ServiceAccountCredentialId, 21),
    service_account_id=SERVICE_ACCOUNT.id,
    lookup_id="abcdefghijklmnop",
    verifier=b"v" * 32,
    salt=b"s" * 16,
    algorithm="scrypt-v1",
    created_by=ACTOR,
    created_at=NOW,
)
ORGANIZATION = Organization(
    id=SCOPE.organization_id,
    name="Example",
    slug="example",
    created_by=ACTOR,
    created_at=NOW,
    updated_at=NOW,
)
MEMBERSHIP = OrganizationMembership(
    id=_id(MembershipId, 7),
    organization_id=SCOPE.organization_id,
    user_id=USER.id,
    role=MembershipRole.OWNER,
    state=MembershipState.ACTIVE,
    created_by=ACTOR,
    created_at=NOW,
    updated_at=NOW,
)
WORKSPACE = Workspace(
    id=SCOPE.workspace_id,
    organization_id=SCOPE.organization_id,
    name="Production",
    slug="production",
    created_by=ACTOR,
    created_at=NOW,
    updated_at=NOW,
)
INCIDENT = Incident(
    id=INCIDENT_ID,
    scope=SCOPE,
    payload=IncidentPayload(
        alert_title="Checkout latency",
        service_name="checkout-api",
        provider_event_id="evt-1",
    ),
    source=IncidentSource("manual", "api", NOW, external_id="evt-1"),
    state=IncidentState.OPEN,
    created_by=ACTOR,
    created_at=NOW,
    updated_at=NOW,
    correlation=CORRELATION,
)
TRIAGE = TriageRun(
    id=TRIAGE_ID,
    scope=SCOPE,
    incident=INCIDENT.reference,
    state=TriageRunState.QUEUED,
    created_by=ACTOR,
    created_at=NOW,
    updated_at=NOW,
    correlation=CORRELATION,
)
EVIDENCE = Evidence(
    id=_id(EvidenceId, 8),
    scope=SCOPE,
    triage_run=TRIAGE.reference,
    type="runbook",
    source="runbooks/checkout.md",
    reason="Relevant procedure",
    created_at=NOW,
)
FEEDBACK = Feedback(
    id=_id(FeedbackId, 9),
    scope=SCOPE,
    triage_run=TRIAGE.reference,
    submitted_by=ACTOR,
    created_at=NOW,
    diagnosis_correct=True,
    actions_useful=True,
    notes="Useful",
)
DOCUMENT = Document(
    id=_id(DocumentId, 10),
    scope=SCOPE,
    name="checkout.md",
    category=DocumentCategory.RUNBOOK,
    state=DocumentState.AVAILABLE,
    created_by=ACTOR,
    created_at=NOW,
    updated_at=NOW,
)
DOCUMENT_VERSION = DocumentVersion(
    id=_id(DocumentVersionId, 11),
    scope=SCOPE,
    document=DOCUMENT.reference,
    version_number=1,
    checksum_sha256="a" * 64,
    size_bytes=42,
    media_type="text/markdown",
    original_filename="checkout.md",
    storage_provider="s3",
    object_key="documents/org/workspace/document/version/source",
    state=DocumentVersionState.AVAILABLE,
    created_by=ACTOR,
    created_at=NOW,
    updated_at=NOW,
    verified_checksum_sha256="a" * 64,
    verified_size_bytes=42,
    verified_media_type="text/markdown",
    finalized_at=NOW,
)
INDEX_VERSION = KnowledgeIndexVersion(
    id=_id(KnowledgeIndexVersionId, 12),
    scope=SCOPE,
    state=KnowledgeIndexState.BUILDING,
    source_document_versions=(DOCUMENT_VERSION.id,),
    created_by=ACTOR,
    created_at=NOW,
    updated_at=NOW,
)
INTEGRATION = Integration(
    id=_id(IntegrationId, 13),
    scope=SCOPE,
    provider="cloudwatch",
    name="Production alarms",
    state=IntegrationState.ACTIVE,
    created_by=ACTOR,
    created_at=NOW,
    updated_at=NOW,
)
JOB = Job(
    id=_id(JobId, 14),
    scope=SCOPE,
    kind=JobKind.TRIAGE,
    subject_type="triage_run",
    subject_id=str(TRIAGE_ID),
    state=JobState.PENDING,
    created_by=ACTOR,
    created_at=NOW,
    updated_at=NOW,
    correlation=CorrelationContext(_id(CorrelationId, 15), job_id=_id(JobId, 14)),
    idempotency_key="triage:5",
    payload_version=1,
    payload=(("triage_run_id", str(TRIAGE_ID)),),
    payload_hash="a" * 64,
    available_at=NOW,
)
ACTION = ActionProposal(
    id=_id(ActionId, 16),
    scope=SCOPE,
    incident=INCIDENT.reference,
    triage_run=TRIAGE.reference,
    proposal_type=ActionProposalType.ACKNOWLEDGE_INCIDENT,
    target=ActionTarget(
        ActionTargetType.INCIDENT,
        str(INCIDENT.id),
        "aira",
        ActionTargetProvenance.INCIDENT,
    ),
    summary="Acknowledge the incident",
    rationale="Derived deterministically from the completed triage result.",
    parameters=AcknowledgeIncidentParameters(),
    risk_level=ActionRiskLevel.LOW,
    reversibility=ActionReversibility.REVERSIBLE,
    policy_status=ActionPolicyStatus.ALLOWED_FOR_REVIEW,
    policy_reason=ActionPolicyReason.READY_FOR_REVIEW,
    lifecycle_state=ActionProposalState.READY_FOR_REVIEW,
    created_by=ACTOR,
    created_at=NOW,
    updated_at=NOW,
    source_result_version=1,
    source_result_hash="a" * 64,
    normalized_action_hash="b" * 64,
    source_recommendation="Acknowledge incident",
)
APPROVAL = Approval(
    id=_id(ApprovalId, 17),
    scope=SCOPE,
    action=ACTION.reference,
    proposal_schema_version=ACTION.proposal_schema_version,
    source_result_version=ACTION.source_result_version,
    source_result_hash=ACTION.source_result_hash,
    normalized_action_hash=ACTION.normalized_action_hash,
    state=ApprovalState.REQUESTED,
    requested_by=ACTOR,
    requested_at=NOW,
    created_at=NOW,
    updated_at=NOW,
    expires_at=NOW + timedelta(hours=1),
)
USAGE = UsageEvent(
    id=_id(UsageEventId, 18),
    scope=SCOPE,
    category="llm_tokens",
    quantity=12,
    unit="token",
    occurred_at=NOW,
    correlation=CORRELATION,
    actor=ACTOR,
    idempotency_key="run:tokens",
)
AUDIT = AuditEvent(
    id=_id(AuditEventId, 19),
    organization_scope=OrganizationScope(SCOPE.organization_id),
    workspace_scope=SCOPE,
    event_type="triage.queued",
    target_type="triage_run",
    target_id=str(TRIAGE_ID),
    actor=ACTOR,
    occurred_at=NOW,
    correlation=CORRELATION,
    details=(("source", "manual"),),
)


@pytest.mark.parametrize(
    ("domain_object", "to_record", "from_record"),
    [
        (USER, mappers.user_to_record, mappers.user_from_record),
        (
            SERVICE_ACCOUNT,
            mappers.service_account_to_record,
            mappers.service_account_from_record,
        ),
        (
            SERVICE_CREDENTIAL,
            mappers.service_account_credential_to_record,
            mappers.service_account_credential_from_record,
        ),
        (
            ORGANIZATION,
            mappers.organization_to_record,
            mappers.organization_from_record,
        ),
        (MEMBERSHIP, mappers.membership_to_record, mappers.membership_from_record),
        (WORKSPACE, mappers.workspace_to_record, mappers.workspace_from_record),
        (INCIDENT, mappers.incident_to_record, mappers.incident_from_record),
        (TRIAGE, mappers.triage_run_to_record, mappers.triage_run_from_record),
        (EVIDENCE, mappers.evidence_to_record, mappers.evidence_from_record),
        (FEEDBACK, mappers.feedback_to_record, mappers.feedback_from_record),
        (DOCUMENT, mappers.document_to_record, mappers.document_from_record),
        (
            DOCUMENT_VERSION,
            mappers.document_version_to_record,
            mappers.document_version_from_record,
        ),
        (INTEGRATION, mappers.integration_to_record, mappers.integration_from_record),
        (JOB, mappers.job_to_record, mappers.job_from_record),
        (ACTION, mappers.action_to_record, mappers.action_from_record),
        (APPROVAL, mappers.approval_to_record, mappers.approval_from_record),
        (USAGE, mappers.usage_event_to_record, mappers.usage_event_from_record),
        (AUDIT, mappers.audit_event_to_record, mappers.audit_event_from_record),
    ],
)
def test_domain_record_round_trip(domain_object, to_record, from_record) -> None:
    assert from_record(to_record(domain_object)) == domain_object


def test_knowledge_index_mapping_keeps_document_version_membership() -> None:
    record = mappers.knowledge_index_to_record(INDEX_VERSION)
    links = mappers.knowledge_index_document_records(INDEX_VERSION)

    restored = mappers.knowledge_index_from_record(
        record,
        [link.document_version_id for link in links],
    )

    assert restored == INDEX_VERSION
