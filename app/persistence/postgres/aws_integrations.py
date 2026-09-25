"""PostgreSQL repository and authorized unit of work for AWS integrations."""

from __future__ import annotations

from types import TracebackType
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.authorization.service import AuthorizedTenantContext
from app.domain.aws_integrations import (
    AwsCapability,
    AwsCapabilityCheck,
    AwsIntegration,
    AwsIntegrationState,
    AwsVerificationError,
    AwsVerificationResult,
)
from app.domain.common import WorkspaceScope
from app.domain.identifiers import IntegrationId, OrganizationId, WorkspaceId
from app.persistence.postgres.mappers import _actor, _actor_columns
from app.persistence.postgres.models import AwsIntegrationRecord
from app.persistence.postgres.repositories import PostgresAuditEventRepository
from app.persistence.postgres.tenant import TenantContext, apply_tenant_context


class AwsIntegrationVersionConflict(RuntimeError):
    pass


class PostgresAwsIntegrationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, integration: AwsIntegration) -> None:
        self._session.add(_to_record(integration))
        self._session.flush()

    def get(self, integration_id: IntegrationId) -> AwsIntegration | None:
        record = self._session.get(AwsIntegrationRecord, UUID(str(integration_id)))
        return _from_record(record) if record else None

    def list(self, *, limit: int) -> list[AwsIntegration]:
        records = self._session.scalars(
            select(AwsIntegrationRecord)
            .order_by(
                AwsIntegrationRecord.created_at.desc(),
                AwsIntegrationRecord.id.desc(),
            )
            .limit(limit)
        ).all()
        return [_from_record(record) for record in records]

    def save(self, integration: AwsIntegration, *, expected_version: int) -> None:
        record = _to_record(integration)
        values = {
            "display_name": record.display_name,
            "aws_account_id": record.aws_account_id,
            "role_arn": record.role_arn,
            "enabled_regions": record.enabled_regions,
            "state": record.state,
            "version": record.version,
            "verification": record.verification,
            "verified_at": record.verified_at,
            "disabled_at": record.disabled_at,
            "updated_at": record.updated_at,
        }
        result = self._session.execute(
            update(AwsIntegrationRecord)
            .where(
                AwsIntegrationRecord.id == UUID(str(integration.id)),
                AwsIntegrationRecord.version == expected_version,
            )
            .values(**values)
        )
        if result.rowcount != 1:
            raise AwsIntegrationVersionConflict("AWS integration version is stale")
        self._session.flush()


class PostgresAwsIntegrationUnitOfWork:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        context: AuthorizedTenantContext,
    ) -> None:
        self._session_factory = session_factory
        self._context = context
        self.session: Session | None = None

    def __enter__(self):
        self.session = self._session_factory()
        self.session.begin()
        apply_tenant_context(
            self.session,
            TenantContext(self._context.organization_id, self._context.workspace_id),
        )
        self.aws_integrations = PostgresAwsIntegrationRepository(self.session)
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


def _to_record(integration: AwsIntegration) -> AwsIntegrationRecord:
    verification = integration.verification
    return AwsIntegrationRecord(
        id=UUID(str(integration.id)),
        organization_id=UUID(str(integration.scope.organization_id)),
        workspace_id=UUID(str(integration.scope.workspace_id)),
        display_name=integration.display_name,
        aws_account_id=integration.aws_account_id,
        role_arn=integration.role_arn,
        external_id=integration.external_id,
        enabled_regions=list(integration.enabled_regions),
        state=integration.state.value,
        version=integration.version,
        verification=_verification_to_json(verification) if verification else None,
        verified_at=verification.verified_at if verification else None,
        disabled_at=integration.disabled_at,
        created_at=integration.created_at,
        updated_at=integration.updated_at,
        **_actor_columns(integration.created_by),
    )


def _from_record(record: AwsIntegrationRecord) -> AwsIntegration:
    return AwsIntegration(
        id=IntegrationId(str(record.id)),
        scope=WorkspaceScope(
            OrganizationId(str(record.organization_id)),
            WorkspaceId(str(record.workspace_id)),
        ),
        display_name=record.display_name,
        aws_account_id=record.aws_account_id,
        role_arn=record.role_arn,
        external_id=record.external_id,
        enabled_regions=tuple(record.enabled_regions),
        state=AwsIntegrationState(record.state),
        version=record.version,
        verification=(
            _verification_from_json(record.verification)
            if record.verification is not None
            else None
        ),
        disabled_at=record.disabled_at,
        created_by=_actor(record.actor_kind, record.actor_id, record.actor_system_name),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _verification_to_json(result: AwsVerificationResult) -> dict:
    return {
        "assume_role_passed": result.assume_role_passed,
        "account_identity_passed": result.account_identity_passed,
        "error_code": result.error_code.value if result.error_code else None,
        "summary": result.summary,
        "verified_at": result.verified_at.isoformat(),
        "checks": [
            {
                "capability": check.capability.value,
                "region": check.region,
                "passed": check.passed,
                "error_code": check.error_code.value if check.error_code else None,
                "summary": check.summary,
            }
            for check in result.checks
        ],
    }


def _verification_from_json(value: dict) -> AwsVerificationResult:
    from datetime import datetime

    return AwsVerificationResult(
        assume_role_passed=bool(value["assume_role_passed"]),
        account_identity_passed=bool(value["account_identity_passed"]),
        checks=tuple(
            AwsCapabilityCheck(
                capability=AwsCapability(check["capability"]),
                region=check["region"],
                passed=bool(check["passed"]),
                error_code=(
                    AwsVerificationError(check["error_code"])
                    if check.get("error_code")
                    else None
                ),
                summary=check.get("summary"),
            )
            for check in value["checks"]
        ),
        verified_at=datetime.fromisoformat(value["verified_at"]),
        error_code=(
            AwsVerificationError(value["error_code"])
            if value.get("error_code")
            else None
        ),
        summary=value.get("summary"),
    )
