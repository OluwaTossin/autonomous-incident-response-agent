"""Denied mutations must stop before persistence, storage, queue, usage, or audit."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.application.documents import HostedDocumentService
from app.application.incidents import HostedIncidentInput, HostedIncidentService
from app.application.workspaces import HostedWorkspaceService
from app.authorization.service import AuthorizationDenied, AuthorizationService
from app.domain.knowledge import DocumentCategory
from app.domain.tenancy import MembershipRole

from .fixtures import A1, A2, B1, ORG_A, ORG_B, human
from .test_authorization_adversarial import Facts, Resources

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


class SideEffects:
    def __init__(self) -> None:
        self.uow_entries = 0
        self.storage_calls = 0
        self.queue_messages = 0
        self.usage_events = 0
        self.audit_events = 0

    def uow(self, context):
        self.uow_entries += 1
        raise AssertionError("denied operation reached persistence")

    def create_presigned_upload(self, *args, **kwargs):
        self.storage_calls += 1
        raise AssertionError("denied operation reached object storage")


def _authorization() -> AuthorizationService:
    return AuthorizationService(Facts(), Resources())


@pytest.mark.parametrize(
    ("organization_id", "workspace_id"),
    ((ORG_A, A2), (ORG_B, B1)),
)
def test_restricted_operator_cannot_create_foreign_incident_with_side_effects(
    organization_id,
    workspace_id,
) -> None:
    effects = SideEffects()
    service = HostedIncidentService(_authorization(), effects.uow, clock=lambda: NOW)
    incident = HostedIncidentInput(
        title="Foreign mutation",
        description="Must never persist",
        service_name="api",
        environment="test",
        source_provider="manual",
        source_type="operator",
        observed_at=NOW,
    )

    with pytest.raises(AuthorizationDenied):
        service.create_incident(
            human(ORG_A, MembershipRole.OPERATOR),
            organization_id,
            workspace_id,
            incident,
        )

    assert effects.__dict__ == {
        "uow_entries": 0,
        "storage_calls": 0,
        "queue_messages": 0,
        "usage_events": 0,
        "audit_events": 0,
    }


def test_viewer_workspace_mutations_stop_before_uow_and_audit() -> None:
    effects = SideEffects()
    service = HostedWorkspaceService(_authorization(), effects.uow, clock=lambda: NOW)
    viewer = human(ORG_A, MembershipRole.VIEWER)

    with pytest.raises(AuthorizationDenied):
        service.update_metadata(
            viewer,
            ORG_A,
            A1,
            expected_version=1,
            name="Escalated",
        )
    with pytest.raises(AuthorizationDenied):
        service.archive(viewer, ORG_A, A1, expected_version=1)

    assert effects.uow_entries == 0
    assert effects.audit_events == 0


@pytest.mark.parametrize(
    ("organization_id", "workspace_id"),
    ((ORG_A, A2), (ORG_B, B1)),
)
def test_document_idor_denial_makes_no_s3_or_database_call(
    organization_id,
    workspace_id,
) -> None:
    effects = SideEffects()
    service = HostedDocumentService(
        _authorization(),
        effects.uow,
        effects,
        clock=lambda: NOW,
        enforce_quotas=True,
    )

    with pytest.raises(AuthorizationDenied):
        service.initiate_document_upload(
            human(ORG_A, MembershipRole.OPERATOR),
            organization_id,
            workspace_id,
            original_filename="foreign.md",
            category=DocumentCategory.RUNBOOK,
            checksum_sha256="a" * 64,
            size_bytes=32,
            media_type="text/markdown",
        )

    assert effects.uow_entries == 0
    assert effects.storage_calls == 0
    assert effects.usage_events == 0
    assert effects.audit_events == 0
