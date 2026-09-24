"""One authorized transaction for durable hosted job operations."""

from __future__ import annotations

from types import TracebackType

from sqlalchemy.orm import Session, sessionmaker

from app.authorization.service import AuthorizedTenantContext
from app.persistence.postgres.job_repositories import (
    PostgresJobDispatchRepository,
    PostgresJobRepository,
)
from app.persistence.postgres.repositories import PostgresAuditEventRepository
from app.persistence.postgres.tenant import TenantContext, apply_tenant_context


class PostgresJobUnitOfWork:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        context: AuthorizedTenantContext,
    ) -> None:
        self._session_factory = session_factory
        self._context = context
        self.session: Session | None = None

    def __enter__(self) -> PostgresJobUnitOfWork:
        self.session = self._session_factory()
        self.session.begin()
        apply_tenant_context(
            self.session,
            TenantContext(self._context.organization_id, self._context.workspace_id),
        )
        self.jobs = PostgresJobRepository(self.session)
        self.dispatches = PostgresJobDispatchRepository(self.session)
        self.audit_events = PostgresAuditEventRepository(self.session)
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
