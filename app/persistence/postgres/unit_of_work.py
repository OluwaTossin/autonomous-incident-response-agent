"""Hosted PostgreSQL unit of work with one transaction-local tenant context."""

from __future__ import annotations

from types import TracebackType

from sqlalchemy.orm import Session, sessionmaker

from app.persistence.postgres.repositories import (
    PostgresAuditEventRepository,
    PostgresIncidentRepository,
    PostgresOrganizationRepository,
    PostgresWorkspaceRepository,
)
from app.persistence.postgres.tenant import TenantContext, apply_tenant_context


class PostgresUnitOfWork:
    """Commit on clean exit and roll back on error; do not span external work."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        tenant: TenantContext,
    ) -> None:
        self._session_factory = session_factory
        self._tenant = tenant
        self.session: Session | None = None

    def __enter__(self) -> PostgresUnitOfWork:
        self.session = self._session_factory()
        self.session.begin()
        apply_tenant_context(self.session, self._tenant)
        self.organizations = PostgresOrganizationRepository(self.session)
        self.workspaces = PostgresWorkspaceRepository(self.session)
        self.incidents = PostgresIncidentRepository(self.session)
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
