"""Hosted domain identifier, actor, and tenancy invariants."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.common import ActorKind, ActorReference, DomainInvariantError, RetentionMarker
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
    ServiceAccountId,
    TriageRunId,
    UsageEventId,
    UserId,
    WorkspaceId,
)
from app.domain.tenancy import (
    MembershipRole,
    MembershipState,
    Organization,
    OrganizationMembership,
    OrganizationState,
    User,
    Workspace,
    WorkspaceState,
)

NOW = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)


def _id(identifier_type, suffix: int):
    return identifier_type(f"00000000-0000-4000-8000-{suffix:012d}")


ID_TYPES = (
    UserId,
    OrganizationId,
    MembershipId,
    WorkspaceId,
    IncidentId,
    TriageRunId,
    EvidenceId,
    FeedbackId,
    DocumentId,
    DocumentVersionId,
    KnowledgeIndexVersionId,
    IntegrationId,
    JobId,
    ActionId,
    ApprovalId,
    ServiceAccountId,
    AuditEventId,
    UsageEventId,
    CorrelationId,
)


@pytest.mark.parametrize("identifier_type", ID_TYPES)
def test_domain_identifiers_are_canonical_and_stringable(identifier_type) -> None:
    identifier = identifier_type("00000000-0000-4000-8000-0000000000AA")

    assert identifier.value == "00000000-0000-4000-8000-0000000000aa"
    assert str(identifier) == identifier.value
    assert identifier_type.parse(identifier.value) == identifier
    assert isinstance(identifier_type.new(), identifier_type)


@pytest.mark.parametrize("value", ["", "not-a-uuid", "00000000-0000-0000-0000-000000000000"])
def test_domain_identifier_rejects_invalid_or_nil_values(value: str) -> None:
    with pytest.raises(ValueError):
        UserId(value)


def test_triage_run_id_round_trips_legacy_triage_id() -> None:
    legacy = "00000000-0000-4000-8000-000000000123"

    hosted = TriageRunId.from_legacy_triage_id(legacy)

    assert hosted.to_legacy_triage_id() == legacy


def test_actor_reference_distinguishes_human_service_account_and_system() -> None:
    human = ActorReference(ActorKind.HUMAN, actor_id=_id(UserId, 1))
    service = ActorReference(
        ActorKind.SERVICE_ACCOUNT,
        actor_id=_id(ServiceAccountId, 2),
    )
    system = ActorReference(ActorKind.SYSTEM, system_name=" triage-worker ")

    assert isinstance(human.actor_id, UserId)
    assert isinstance(service.actor_id, ServiceAccountId)
    assert system.system_name == "triage-worker"

    with pytest.raises(DomainInvariantError):
        ActorReference(ActorKind.HUMAN, actor_id=_id(ServiceAccountId, 3))
    with pytest.raises(DomainInvariantError):
        ActorReference(ActorKind.SYSTEM, system_name=" ")


def test_retention_marker_requires_domain_valid_values() -> None:
    marker = RetentionMarker(
        policy_ref=" security-90-days ",
        retain_until=NOW + timedelta(days=90),
    )

    assert marker.policy_ref == "security-90-days"
    with pytest.raises(DomainInvariantError, match="timezone-aware"):
        RetentionMarker(retain_until=datetime(2026, 9, 23, 10, 0))


def test_tenancy_entities_expose_scope_and_are_immutable() -> None:
    actor = ActorReference(ActorKind.HUMAN, actor_id=_id(UserId, 1))
    organization = Organization(
        id=_id(OrganizationId, 10),
        name="Example Operations",
        slug="example-ops",
        created_by=actor,
        created_at=NOW,
        updated_at=NOW,
    )
    workspace = Workspace(
        id=_id(WorkspaceId, 11),
        organization_id=organization.id,
        name="Production",
        slug="production",
        created_by=actor,
        created_at=NOW,
        updated_at=NOW,
    )

    assert workspace.scope.organization_id == organization.id
    assert workspace.scope.workspace_id == workspace.id
    assert organization.archive(at=NOW).state is OrganizationState.ARCHIVED
    assert workspace.archive(at=NOW).state is WorkspaceState.ARCHIVED
    with pytest.raises(FrozenInstanceError):
        workspace.name = "Changed"  # type: ignore[misc]


def test_user_and_membership_lifecycle() -> None:
    user_id = _id(UserId, 1)
    actor = ActorReference(ActorKind.HUMAN, actor_id=user_id)
    user = User(
        id=user_id,
        email="operator@example.com",
        display_name="Operator",
        identity_provider="managed-idp",
        provider_subject="subject-1",
        created_at=NOW,
    )
    membership = OrganizationMembership(
        id=_id(MembershipId, 2),
        organization_id=_id(OrganizationId, 3),
        user_id=user.id,
        role=MembershipRole.OPERATOR,
        state=MembershipState.INVITED,
        created_by=actor,
        created_at=NOW,
        updated_at=NOW,
    )

    active = membership.transition(MembershipState.ACTIVE, at=NOW)
    suspended = active.transition(MembershipState.SUSPENDED, at=NOW)
    revoked = suspended.transition(MembershipState.REVOKED, at=NOW)

    assert revoked.state is MembershipState.REVOKED
    with pytest.raises(DomainInvariantError):
        revoked.transition(MembershipState.ACTIVE, at=NOW)
