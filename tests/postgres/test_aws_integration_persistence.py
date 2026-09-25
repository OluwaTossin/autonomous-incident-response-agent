"""Real PostgreSQL AWS integration persistence, audit, and RLS tests."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update

from app.application.aws_integrations import HostedAwsIntegrationService
from app.authorization.service import AuthorizationService
from app.domain.aws_integrations import AwsIntegrationState
from app.integrations.aws import AwsCallerIdentity
from app.persistence.postgres.authorization import (
    PostgresAuthorizationFactsRepository,
    PostgresTenantResourceValidator,
)
from app.persistence.postgres.aws_integrations import PostgresAwsIntegrationUnitOfWork
from app.persistence.postgres.models import AuditEventRecord, AwsIntegrationRecord
from app.persistence.postgres.tenant import TenantContext, tenant_transaction

from .conftest import PostgresTestDatabase
from .test_document_persistence import NOW, _setup
from .test_workspace_persistence import _service as workspace_service


class Session:
    def caller_identity(self):
        return AwsCallerIdentity(
            "123456789012",
            "arn:aws:sts::123456789012:assumed-role/aira-read/verify",
        )

    def probe(self, capability, region):
        return None


class Assumer:
    def assume_role(self, **values):
        return Session()


def _service(runtime_session_factory):
    authorization = AuthorizationService(
        PostgresAuthorizationFactsRepository(runtime_session_factory),
        PostgresTenantResourceValidator(runtime_session_factory),
    )
    return HostedAwsIntegrationService(
        authorization,
        lambda context: PostgresAwsIntegrationUnitOfWork(
            runtime_session_factory, context
        ),
        Assumer(),
        trusted_principal_arn="arn:aws:iam::111122223333:role/aira-hosted-api",
        clock=lambda: NOW,
        external_id_factory=lambda: "p" * 43,
    )


def test_aws_integration_lifecycle_audit_and_verification_are_durable(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    actor, organization_id, _, workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 260
    )
    service = _service(runtime_session_factory)
    created = service.create(
        actor,
        organization_id,
        workspace.id,
        display_name="Production AWS",
        aws_account_id="123456789012",
        enabled_regions=("eu-west-2",),
    )
    configured = service.update(
        actor,
        organization_id,
        workspace.id,
        created.id,
        expected_version=created.version,
        role_arn="arn:aws:iam::123456789012:role/aira-read",
    )
    ready = service.verify(
        actor,
        organization_id,
        workspace.id,
        created.id,
        expected_version=configured.version,
    )

    assert ready.state is AwsIntegrationState.READY
    assert ready.verification and ready.verification.succeeded
    assert service.get(actor, organization_id, workspace.id, ready.id) == ready
    assert service.list(actor, organization_id, workspace.id) == (ready,)
    with postgres_database.migration_engine.connect() as connection:
        events = connection.execute(
            select(AuditEventRecord.event_type).where(
                AuditEventRecord.target_id == str(ready.id)
            )
        ).scalars().all()
    assert events == [
        "aws_integration.created",
        "aws_integration.configuration_updated",
        "aws_integration.verification_succeeded",
    ]


def test_aws_integration_rls_fails_closed_across_workspaces(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    actor, organization_id, _, workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 261
    )
    _, second_org, _, second_workspace, _, _ = _setup(
        postgres_database, runtime_session_factory, 262
    )
    created = _service(runtime_session_factory).create(
        actor,
        organization_id,
        workspace.id,
        display_name="Production AWS",
        aws_account_id="123456789012",
        enabled_regions=("eu-west-2",),
    )
    same_org_workspace = workspace_service(runtime_session_factory).create(
        actor,
        organization_id,
        name="Second workspace",
        slug="second-workspace",
    )
    with runtime_session_factory.begin() as session:
        assert session.scalar(select(func.count()).select_from(AwsIntegrationRecord)) == 0
    with tenant_transaction(
        runtime_session_factory,
        TenantContext(organization_id, same_org_workspace.id),
    ) as session:
        assert session.get(AwsIntegrationRecord, UUID(str(created.id))) is None
        result = session.execute(
            update(AwsIntegrationRecord)
            .where(AwsIntegrationRecord.id == UUID(str(created.id)))
            .values(display_name="Cross-workspace update")
        )
        assert result.rowcount == 0
    with tenant_transaction(
        runtime_session_factory, TenantContext(second_org, second_workspace.id)
    ) as session:
        assert session.get(AwsIntegrationRecord, UUID(str(created.id))) is None
        assert session.scalar(select(func.count()).select_from(AwsIntegrationRecord)) == 0
