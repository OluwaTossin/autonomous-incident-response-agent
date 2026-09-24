"""Authorized hosted FAISS bundle publication, activation, and rollback."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from app.auth.context import ActorContext
from app.authorization.permissions import Permission
from app.authorization.service import AuthorizationService, AuthorizedTenantContext
from app.domain.common import WorkspaceScope
from app.domain.identifiers import KnowledgeIndexVersionId, OrganizationId, WorkspaceId
from app.domain.knowledge import KnowledgeIndexState, KnowledgeIndexVersion
from app.knowledge.bundle import HostedKnowledgeBundleBuilder
from app.knowledge.contracts import (
    HostedKnowledgeIndexReference,
    KnowledgeSourceReference,
    PublishedKnowledgeIndexReference,
    SystemCorpusPolicy,
)
from app.knowledge.storage import KnowledgeBundlePublisher

logger = logging.getLogger(__name__)


class KnowledgeBundleNotFound(LookupError):
    """A published index version is unavailable in the authorized workspace."""


class KnowledgeLifecycleObserver(Protocol):
    def record(self, event: str, duration_ms: int, outcome: str) -> None: ...


class NoopKnowledgeLifecycleObserver:
    def record(self, event: str, duration_ms: int, outcome: str) -> None:
        return None


class KnowledgeBundleRepository(Protocol):
    def select_eligible_sources(
        self, context: AuthorizedTenantContext
    ) -> tuple[KnowledgeSourceReference, ...]: ...

    def create_build(
        self,
        context: AuthorizedTenantContext,
        index: KnowledgeIndexVersion,
        *,
        at: datetime,
    ) -> None: ...

    def mark_ready(self, context, index_version_id, publication, *, at): ...
    def mark_failed(self, context, index_version_id, reason, *, at): ...
    def activate(
        self, context, index_version_id, *, at, rollback=False
    ) -> PublishedKnowledgeIndexReference: ...
    def resolve_publication(
        self, context, index_version_id
    ) -> PublishedKnowledgeIndexReference | None: ...
    def resolve_active_publication(
        self, context
    ) -> PublishedKnowledgeIndexReference | None: ...
    def record_integrity_failure(self, context, index_version_id, *, at): ...


class HostedKnowledgeBundleService:
    def __init__(
        self,
        authorization: AuthorizationService,
        repository: KnowledgeBundleRepository,
        builder: HostedKnowledgeBundleBuilder,
        publisher: KnowledgeBundlePublisher,
        *,
        system_corpus: SystemCorpusPolicy = SystemCorpusPolicy(),
        observer: KnowledgeLifecycleObserver = NoopKnowledgeLifecycleObserver(),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._authorization = authorization
        self._repository = repository
        self._builder = builder
        self._publisher = publisher
        self._system_corpus = system_corpus
        self._observer = observer
        self._clock = clock
        self._monotonic = monotonic

    def build_publish_activate(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
    ) -> PublishedKnowledgeIndexReference:
        context = self._authorize(
            actor, organization_id, workspace_id, Permission.KNOWLEDGE_MANAGE
        )
        tenant_sources = self._repository.select_eligible_sources(context)
        sources = tenant_sources + self._system_corpus.selected_sources()
        now = self._clock()
        index = KnowledgeIndexVersion(
            id=KnowledgeIndexVersionId.new(),
            scope=WorkspaceScope(organization_id, workspace_id),
            state=KnowledgeIndexState.BUILDING,
            source_document_versions=tuple(
                source.document_version_id
                for source in tenant_sources
                if source.document_version_id is not None
            ),
            created_by=actor.actor,
            created_at=now,
            updated_at=now,
        )
        self._repository.create_build(context, index, at=now)
        reference = HostedKnowledgeIndexReference(
            index.scope, index.id, index.source_document_versions
        )
        phase = "bundle_build"
        phase_started = self._monotonic()
        try:
            with self._builder.build(context, reference, sources) as bundle:
                self._observe(phase, phase_started, "succeeded")
                phase = "bundle_publish"
                phase_started = self._monotonic()
                publication = self._publisher.publish(reference, bundle)
            self._repository.mark_ready(
                context, index.id, publication, at=self._clock()
            )
        except Exception as exc:
            self._repository.mark_failed(
                context,
                index.id,
                "Bundle publication or integrity verification failed",
                at=self._clock(),
            )
            self._observe(phase, phase_started, "failed")
            logger.warning(
                "knowledge bundle publication failed: exception_type=%s",
                type(exc).__name__,
            )
            raise
        self._observe(phase, phase_started, "succeeded")
        activation_started = self._monotonic()
        try:
            activated = self._repository.activate(
                context, index.id, at=self._clock(), rollback=False
            )
        except Exception:
            self._observe("bundle_activation", activation_started, "failed")
            raise
        self._observe("bundle_activation", activation_started, "succeeded")
        return activated

    def rollback(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        index_version_id: KnowledgeIndexVersionId,
    ) -> PublishedKnowledgeIndexReference:
        context = self._authorize(
            actor, organization_id, workspace_id, Permission.KNOWLEDGE_MANAGE
        )
        candidate = self._repository.resolve_publication(context, index_version_id)
        if candidate is None:
            raise KnowledgeBundleNotFound("Published knowledge bundle not found")
        self._publisher.verify(candidate.index, candidate.publication)
        return self._repository.activate(
            context, index_version_id, at=self._clock(), rollback=True
        )

    def resolve_active(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
    ) -> PublishedKnowledgeIndexReference:
        context = self._authorize(
            actor, organization_id, workspace_id, Permission.KNOWLEDGE_READ
        )
        reference = self._repository.resolve_active_publication(context)
        if reference is None:
            raise KnowledgeBundleNotFound("Active knowledge bundle not found")
        started = self._monotonic()
        try:
            self._publisher.verify(reference.index, reference.publication)
        except Exception:
            self._repository.record_integrity_failure(
                context, reference.index.index_version_id, at=self._clock()
            )
            self._observe("bundle_verify", started, "failed")
            raise
        self._observe("bundle_verify", started, "succeeded")
        return reference

    def _authorize(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        permission: Permission,
    ) -> AuthorizedTenantContext:
        return self._authorization.authorize(
            actor, organization_id, permission, workspace_id=workspace_id
        )

    def _observe(self, event: str, started: float, outcome: str) -> None:
        duration_ms = max(0, int((self._monotonic() - started) * 1000))
        self._observer.record(event, duration_ms, outcome)
