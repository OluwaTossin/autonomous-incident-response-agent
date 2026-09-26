"""One authorized transaction for hosted document metadata."""

from __future__ import annotations

from types import TracebackType

from sqlalchemy.orm import Session, sessionmaker

from app.authorization.service import AuthorizedTenantContext
from app.persistence.postgres.document_repositories import (
    PostgresDocumentRepository,
    PostgresDocumentVersionRepository,
)
from app.persistence.postgres.repositories import PostgresAuditEventRepository
from app.persistence.postgres.usage import PostgresUsageQuotaRepository
from app.persistence.postgres.tenant import TenantContext, apply_tenant_context


class PostgresDocumentUnitOfWork:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        context: AuthorizedTenantContext,
        quota_defaults=None,
        quota_observer=None,
    ) -> None:
        self._session_factory = session_factory
        self._context = context
        self._quota_defaults = quota_defaults
        self._quota_observer = quota_observer
        self.session: Session | None = None

    def __enter__(self) -> PostgresDocumentUnitOfWork:
        self.session = self._session_factory()
        self.session.begin()
        apply_tenant_context(
            self.session,
            TenantContext(self._context.organization_id, self._context.workspace_id),
        )
        self.documents = PostgresDocumentRepository(self.session)
        self.document_versions = PostgresDocumentVersionRepository(self.session)
        self.audit_events = PostgresAuditEventRepository(self.session)
        self.usage = PostgresUsageQuotaRepository(
            self.session, self._context, self._quota_defaults, self._quota_observer
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.session is None:
            return
        try:
            if exc_type is None:
                self.session.commit()
            else:
                self.session.rollback()
        finally:
            self.session.close()
            self.session = None
