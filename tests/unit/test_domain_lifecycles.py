"""Knowledge, integration, job, action, usage, and audit lifecycle tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.domain.actions import (
    ActionReference,
    Approval,
    ApprovalState,
)
from app.domain.common import (
    ActorKind,
    ActorReference,
    CorrelationContext,
    DomainInvariantError,
    InvalidStateTransition,
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
    IntegrationId,
    JobId,
    KnowledgeIndexVersionId,
    OrganizationId,
    UsageEventId,
    ServiceAccountId,
    UserId,
    WorkspaceId,
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
from app.domain.operations import (
    Integration,
    IntegrationState,
    Job,
    JobErrorCategory,
    JobFailure,
    JobKind,
    JobResultReference,
    JobState,
)

NOW = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=1)
DONE = NOW + timedelta(minutes=2)


def _id(identifier_type, suffix: int):
    return identifier_type(f"00000000-0000-4000-8000-{suffix:012d}")


def _scope(organization: int = 1, workspace: int = 2) -> WorkspaceScope:
    return WorkspaceScope(
        _id(OrganizationId, organization), _id(WorkspaceId, workspace)
    )


def _actor() -> ActorReference:
    return ActorReference(ActorKind.HUMAN, actor_id=_id(UserId, 3))


def _other_actor() -> ActorReference:
    return ActorReference(ActorKind.HUMAN, actor_id=_id(UserId, 30))


def _document() -> Document:
    return Document(
        id=_id(DocumentId, 4),
        scope=_scope(),
        name="checkout.md",
        category=DocumentCategory.RUNBOOK,
        state=DocumentState.PENDING_UPLOAD,
        created_by=_actor(),
        created_at=NOW,
        updated_at=NOW,
    )


def _index() -> KnowledgeIndexVersion:
    return KnowledgeIndexVersion(
        id=_id(KnowledgeIndexVersionId, 6),
        scope=_scope(),
        state=KnowledgeIndexState.BUILDING,
        source_document_versions=(_id(DocumentVersionId, 5),),
        created_by=_actor(),
        created_at=NOW,
        updated_at=NOW,
    )


def _job() -> Job:
    job_id = _id(JobId, 8)
    return Job(
        id=job_id,
        scope=_scope(),
        kind=JobKind.TRIAGE,
        subject_type="triage_run",
        subject_id="00000000-0000-4000-8000-000000000099",
        state=JobState.PENDING,
        created_by=_actor(),
        created_at=NOW,
        updated_at=NOW,
        correlation=CorrelationContext(_id(CorrelationId, 9), job_id=job_id),
        idempotency_key="triage:99",
        payload_version=1,
        payload=(("triage_run_id", "00000000-0000-4000-8000-000000000099"),),
        payload_hash="a" * 64,
        available_at=NOW,
    )


def _action_reference(suffix: int = 10) -> ActionReference:
    return ActionReference(_id(ActionId, suffix), _scope())


def test_document_and_version_lifecycle_and_scope() -> None:
    pending = _document()
    available = pending.mark_available(at=LATER)
    archived = available.archive(at=DONE)
    version = DocumentVersion(
        id=_id(DocumentVersionId, 5),
        scope=pending.scope,
        document=pending.reference,
        version_number=1,
        checksum_sha256="a" * 64,
        size_bytes=42,
        media_type="text/markdown",
        original_filename="checkout.md",
        storage_provider="s3",
        object_key="documents/org/workspace/document/version/source",
        state=DocumentVersionState.PENDING_UPLOAD,
        created_by=_actor(),
        created_at=NOW,
        updated_at=NOW,
    )

    assert version.document == pending.reference
    assert archived.state is DocumentState.ARCHIVED
    with pytest.raises(InvalidStateTransition):
        archived.mark_available(at=DONE)
    with pytest.raises(DomainInvariantError, match="same scope"):
        DocumentVersion(
            id=_id(DocumentVersionId, 7),
            scope=_scope(9, 9),
            document=pending.reference,
            version_number=1,
            checksum_sha256="b" * 64,
            size_bytes=1,
            media_type="text/plain",
            original_filename="other.txt",
            storage_provider="s3",
            object_key="documents/org/workspace/document/other/source",
            state=DocumentVersionState.PENDING_UPLOAD,
            created_by=_actor(),
            created_at=NOW,
            updated_at=NOW,
        )


def test_knowledge_index_activation_failure_and_terminal_states() -> None:
    ready = _index().mark_ready(
        published_at=LATER,
        manifest_schema_version=1,
        artifact_prefix="knowledge-indexes/org/workspace/index/",
        manifest_checksum_sha256="a" * 64,
    )
    active = ready.activate(at=DONE)
    inactive = active.deactivate(at=DONE + timedelta(minutes=1))
    failed = _index().fail("invalid bundle", at=LATER)

    assert active.activated_at == DONE
    assert inactive.activated_at == DONE
    assert inactive.superseded_at == DONE + timedelta(minutes=1)
    assert failed.failure_reason == "invalid bundle"
    with pytest.raises(InvalidStateTransition):
        failed.activate(at=DONE)
    assert (
        inactive.activate(at=DONE + timedelta(minutes=2)).state
        is KnowledgeIndexState.ACTIVE
    )


def test_integration_can_disable_and_recover_from_error() -> None:
    integration = Integration(
        id=_id(IntegrationId, 7),
        scope=_scope(),
        provider="cloudwatch",
        name="Production alarms",
        state=IntegrationState.ACTIVE,
        created_by=_actor(),
        created_at=NOW,
        updated_at=NOW,
    )

    errored = integration.transition(
        IntegrationState.ERROR, at=LATER, error="access denied"
    )
    recovered = errored.transition(IntegrationState.ACTIVE, at=DONE)
    disabled = recovered.transition(IntegrationState.DISABLED, at=DONE)

    assert disabled.state is IntegrationState.DISABLED
    assert recovered.last_error is None
    with pytest.raises(InvalidStateTransition):
        disabled.transition(IntegrationState.ERROR, at=DONE, error="x")


def test_job_lifecycle_is_queue_implementation_independent_and_terminal() -> None:
    token = UUID("00000000-0000-4000-8000-000000000010")
    claimed = _job().claim(
        worker_id="worker-1",
        claim_token=token,
        lease_expires_at=DONE + timedelta(minutes=1),
        at=LATER,
    )
    succeeded = claimed.succeed(
        token,
        JobResultReference("triage_run", _job().subject_id),
        at=DONE,
    )
    failed = claimed.fail_attempt(
        token,
        JobFailure(
            "llm_timeout",
            JobErrorCategory.INTERNAL,
            False,
            "LLM request timed out",
        ),
        next_available_at=DONE,
        at=DONE,
    )
    cancelled = _job().request_cancel(at=LATER)

    assert succeeded.state is JobState.SUCCEEDED
    assert failed.last_error.code == "llm_timeout"
    assert cancelled.started_at is None
    with pytest.raises(DomainInvariantError, match="Terminal"):
        succeeded.request_cancel(at=DONE)


def test_future_approval_decision_is_terminal() -> None:
    approval = Approval(
        id=_id(ApprovalId, 11),
        scope=_scope(),
        action=_action_reference(),
        proposal_schema_version=1,
        source_result_version=1,
        source_result_hash="a" * 64,
        normalized_action_hash="b" * 64,
        state=ApprovalState.REQUESTED,
        requested_by=_actor(),
        requested_at=NOW,
        created_at=NOW,
        updated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )

    approved = approval.approve(_other_actor(), at=LATER)
    assert approved.state is ApprovalState.APPROVED
    with pytest.raises(InvalidStateTransition):
        approved.reject(_other_actor(), "changed mind", at=DONE)


def test_service_account_cannot_approve_consequential_action() -> None:
    approval = Approval(
        id=_id(ApprovalId, 11),
        scope=_scope(),
        action=_action_reference(),
        proposal_schema_version=1,
        source_result_version=1,
        source_result_hash="a" * 64,
        normalized_action_hash="b" * 64,
        state=ApprovalState.REQUESTED,
        requested_by=_actor(),
        requested_at=NOW,
        created_at=NOW,
        updated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    service_actor = ActorReference(
        ActorKind.SERVICE_ACCOUNT,
        actor_id=_id(ServiceAccountId, 12),
    )

    with pytest.raises(DomainInvariantError, match="human actor"):
        approval.approve(service_actor, at=LATER)


def test_approval_expiry_is_time_bounded() -> None:
    approval = Approval(
        id=_id(ApprovalId, 11),
        scope=_scope(),
        action=_action_reference(),
        proposal_schema_version=1,
        source_result_version=1,
        source_result_hash="a" * 64,
        normalized_action_hash="b" * 64,
        state=ApprovalState.REQUESTED,
        requested_by=_actor(),
        requested_at=NOW,
        created_at=NOW,
        updated_at=NOW,
        expires_at=LATER,
    )

    with pytest.raises(DomainInvariantError, match="before expires_at"):
        approval.expire(at=NOW)
    expired = approval.expire(at=LATER)
    assert expired.state is ApprovalState.EXPIRED


def test_usage_and_audit_events_are_tenant_scoped_and_attributed() -> None:
    scope = _scope()
    correlation = CorrelationContext(_id(CorrelationId, 20))
    usage = UsageEvent(
        id=_id(UsageEventId, 21),
        scope=scope,
        category="llm_input_tokens",
        quantity=125,
        unit="token",
        occurred_at=NOW,
        correlation=correlation,
        actor=_actor(),
        idempotency_key="run-1:tokens",
    )
    audit = AuditEvent(
        id=_id(AuditEventId, 22),
        organization_scope=OrganizationScope(scope.organization_id),
        workspace_scope=scope,
        event_type="triage.started",
        target_type="triage_run",
        target_id="run-1",
        actor=_actor(),
        occurred_at=NOW,
        correlation=correlation,
    )

    assert usage.scope == scope
    assert audit.actor == _actor()

    with pytest.raises(DomainInvariantError, match="belong to the audit organization"):
        AuditEvent(
            id=_id(AuditEventId, 23),
            organization_scope=OrganizationScope(_id(OrganizationId, 99)),
            workspace_scope=scope,
            event_type="workspace.updated",
            target_type="workspace",
            target_id=str(scope.workspace_id),
            actor=_actor(),
            occurred_at=NOW,
            correlation=correlation,
        )
