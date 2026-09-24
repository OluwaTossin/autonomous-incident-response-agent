"""Hosted knowledge boundary, authorization, and policy tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.application.knowledge import (
    HostedKnowledgeService,
    KnowledgeScopeViolation,
)
from app.auth.context import ActorContext, AuthenticationMethod
from app.authorization.service import (
    AuthorizationDenied,
    AuthorizationService,
    HumanAuthorizationFacts,
)
from app.domain.common import ActorKind, ActorReference, WorkspaceScope
from app.domain.identifiers import (
    DocumentId,
    DocumentVersionId,
    KnowledgeIndexVersionId,
    MembershipId,
    OrganizationId,
    UserId,
    WorkspaceId,
)
from app.domain.tenancy import MembershipRole, WorkspaceAccessMode
from app.knowledge.contracts import (
    HostedKnowledgeIndexReference,
    KnowledgeSourceOrigin,
    KnowledgeSourceReference,
    SystemCorpusPolicy,
)


def _id(identifier_type, suffix: int):
    return identifier_type(f"00000000-0000-4000-8000-{suffix:012d}")


ORG = _id(OrganizationId, 1)
WORKSPACE = _id(WorkspaceId, 2)
OTHER_WORKSPACE = _id(WorkspaceId, 3)
SCOPE = WorkspaceScope(ORG, WORKSPACE)


def _actor() -> ActorContext:
    return ActorContext(
        actor=ActorReference(ActorKind.HUMAN, actor_id=_id(UserId, 4)),
        authentication_method=AuthenticationMethod.OIDC,
        issuer="https://issuer.example",
        external_subject="knowledge-operator",
    )


class Facts:
    active = True

    def human_facts(self, actor, organization_id, workspace_id):
        if not self.active or organization_id != ORG:
            return None
        return HumanAuthorizationFacts(
            _id(MembershipId, 5),
            MembershipRole.OPERATOR,
            WorkspaceAccessMode.ALL,
            True,
        )

    def service_account_facts(self, actor, organization_id, workspace_id):
        return None

    def invited_membership_id(self, actor, organization_id):
        return None

    def visible_organization_ids(self, actor):
        return (ORG,) if self.active else ()


class Resources:
    active = True

    def is_active(self, organization_id, workspace_id):
        return self.active and organization_id == ORG and workspace_id == WORKSPACE


class Repository:
    def __init__(self) -> None:
        self.index = HostedKnowledgeIndexReference(
            SCOPE,
            _id(KnowledgeIndexVersionId, 6),
            (_id(DocumentVersionId, 7),),
        )
        self.sources = (
            KnowledgeSourceReference(
                KnowledgeSourceOrigin.TENANT,
                "checkout.md",
                "runbook",
                scope=SCOPE,
                document_id=_id(DocumentId, 8),
                document_version_id=_id(DocumentVersionId, 7),
                checksum_sha256="a" * 64,
                size_bytes=42,
                media_type="text/markdown",
            ),
        )
        self.contexts = []

    def resolve_active_index(self, context):
        self.contexts.append(context)
        return self.index

    def select_eligible_sources(self, context):
        self.contexts.append(context)
        return self.sources


def _service(repository, *, resources=None, system_corpus=SystemCorpusPolicy()):
    return HostedKnowledgeService(
        AuthorizationService(Facts(), resources or Resources()),
        repository,
        system_corpus=system_corpus,
    )


def test_hosted_index_and_sources_require_fresh_authorized_workspace_context() -> None:
    repository = Repository()
    service = _service(repository)

    assert service.resolve_active_index(_actor(), ORG, WORKSPACE) == repository.index
    selection = service.select_index_sources(_actor(), ORG, WORKSPACE)

    assert selection.tenant_sources == repository.sources
    assert [context.workspace_id for context in repository.contexts] == [
        WORKSPACE,
        WORKSPACE,
    ]
    with pytest.raises(AuthorizationDenied):
        service.resolve_active_index(_actor(), ORG, OTHER_WORKSPACE)


def test_archived_workspace_and_repository_scope_mismatch_fail_closed() -> None:
    repository = Repository()
    resources = Resources()
    resources.active = False
    with pytest.raises(AuthorizationDenied):
        _service(repository, resources=resources).resolve_active_index(
            _actor(), ORG, WORKSPACE
        )

    repository.index = replace(
        repository.index, scope=WorkspaceScope(ORG, OTHER_WORKSPACE)
    )
    with pytest.raises(KnowledgeScopeViolation):
        _service(repository).resolve_active_index(_actor(), ORG, WORKSPACE)


def test_system_corpus_is_explicit_attributable_and_disabled_by_default() -> None:
    system_source = KnowledgeSourceReference(
        KnowledgeSourceOrigin.SYSTEM,
        "decisions/security.md",
        "decision",
        system_source_id="aira-decisions/security",
    )
    assert SystemCorpusPolicy(sources=(system_source,)).selected_sources() == ()
    enabled = SystemCorpusPolicy(enabled=True, sources=(system_source,))

    selection = _service(Repository(), system_corpus=enabled).select_index_sources(
        _actor(), ORG, WORKSPACE
    )

    assert selection.system_sources == (system_source,)
    assert selection.system_sources[0].origin is KnowledgeSourceOrigin.SYSTEM


def test_tenant_source_contract_rejects_incomplete_provenance() -> None:
    with pytest.raises(ValueError, match="verified document provenance"):
        KnowledgeSourceReference(
            KnowledgeSourceOrigin.TENANT,
            "checkout.md",
            "runbook",
            scope=SCOPE,
        )
