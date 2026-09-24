"""Authorized hosted knowledge-index and source selection boundaries."""

from __future__ import annotations

from typing import Protocol

from app.auth.context import ActorContext
from app.authorization.permissions import Permission
from app.authorization.service import AuthorizationService, AuthorizedTenantContext
from app.domain.common import WorkspaceScope
from app.domain.identifiers import OrganizationId, WorkspaceId
from app.knowledge.contracts import (
    HostedKnowledgeIndexReference,
    KnowledgeSourceOrigin,
    KnowledgeSourceReference,
    KnowledgeSourceSelection,
    SystemCorpusPolicy,
)


class ActiveKnowledgeIndexNotFound(LookupError):
    """No active knowledge index exists in the authorized workspace."""


class KnowledgeScopeViolation(RuntimeError):
    """A repository returned knowledge outside its authorized tenant scope."""


class HostedKnowledgeRepository(Protocol):
    def resolve_active_index(
        self, context: AuthorizedTenantContext
    ) -> HostedKnowledgeIndexReference | None: ...

    def select_eligible_sources(
        self, context: AuthorizedTenantContext
    ) -> tuple[KnowledgeSourceReference, ...]: ...


class HostedKnowledgeService:
    """Authorize each hosted operation before resolving tenant knowledge."""

    def __init__(
        self,
        authorization: AuthorizationService,
        repository: HostedKnowledgeRepository,
        *,
        system_corpus: SystemCorpusPolicy = SystemCorpusPolicy(),
    ) -> None:
        self._authorization = authorization
        self._repository = repository
        self._system_corpus = system_corpus

    def resolve_active_index(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
    ) -> HostedKnowledgeIndexReference:
        context = self._authorization.authorize(
            actor,
            organization_id,
            Permission.KNOWLEDGE_READ,
            workspace_id=workspace_id,
        )
        reference = self._repository.resolve_active_index(context)
        if reference is None:
            raise ActiveKnowledgeIndexNotFound("Active knowledge index not found")
        self._require_scope(reference.scope, context)
        return reference

    def select_index_sources(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
    ) -> KnowledgeSourceSelection:
        context = self._authorization.authorize(
            actor,
            organization_id,
            Permission.KNOWLEDGE_MANAGE,
            workspace_id=workspace_id,
        )
        tenant_sources = self._repository.select_eligible_sources(context)
        for source in tenant_sources:
            if (
                source.origin is not KnowledgeSourceOrigin.TENANT
                or source.scope is None
            ):
                raise KnowledgeScopeViolation(
                    "Hosted repository returned a non-tenant source"
                )
            self._require_scope(source.scope, context)
        return KnowledgeSourceSelection(
            tenant_sources=tenant_sources,
            system_sources=self._system_corpus.selected_sources(),
        )

    @staticmethod
    def _require_scope(scope: WorkspaceScope, context: AuthorizedTenantContext) -> None:
        expected = WorkspaceScope(
            context.organization_id,
            context.workspace_id,
        )
        if scope != expected:
            raise KnowledgeScopeViolation(
                "Knowledge result does not match the authorized workspace"
            )
