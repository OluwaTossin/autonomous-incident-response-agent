"""Authorized PostgreSQL transaction for hosted incident and triage state."""

from __future__ import annotations

from types import TracebackType

from sqlalchemy.orm import Session, sessionmaker

from app.authorization.service import AuthorizedTenantContext
from app.persistence.postgres.incident_repositories import (
    PostgresEvidenceRepository,
    PostgresFeedbackRepository,
    PostgresHostedIncidentRepository,
    PostgresTriageRunRepository,
)
from app.persistence.postgres.alert_ingestion import PostgresAlertReceiptRepository
from app.persistence.postgres.aws_integrations import PostgresAwsIntegrationRepository
from app.persistence.postgres.incident_context import PostgresIncidentContextRepository
from app.persistence.postgres.job_repositories import (
    PostgresJobDispatchRepository,
    PostgresJobRepository,
)
from app.persistence.postgres.repositories import PostgresAuditEventRepository
from app.persistence.postgres.tenant import TenantContext, apply_tenant_context


class PostgresHostedIncidentUnitOfWork:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        context: AuthorizedTenantContext,
    ) -> None:
        if context.workspace_id is None:
            raise ValueError("Hosted incident transactions require workspace scope")
        self._session_factory = session_factory
        self._context = context
        self.session: Session | None = None

    def __enter__(self) -> PostgresHostedIncidentUnitOfWork:
        self.session = self._session_factory()
        self.session.begin()
        apply_tenant_context(
            self.session,
            TenantContext(self._context.organization_id, self._context.workspace_id),
        )
        self.incidents = PostgresHostedIncidentRepository(self.session)
        self.triage_runs = PostgresTriageRunRepository(self.session)
        self.evidence = PostgresEvidenceRepository(self.session)
        self.context_snapshots = PostgresIncidentContextRepository(self.session)
        self.alert_receipts = PostgresAlertReceiptRepository(self.session)
        self.aws_integrations = PostgresAwsIntegrationRepository(self.session)
        self.feedback = PostgresFeedbackRepository(self.session)
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
