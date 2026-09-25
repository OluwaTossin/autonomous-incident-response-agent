"""Real PostgreSQL execution-intent idempotency, immutability, and RLS evidence."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from app.application.execution_intents import HostedExecutionIntentService
from app.authorization.service import AuthorizationService
from app.persistence.postgres.authorization import (
    PostgresAuthorizationFactsRepository,
    PostgresTenantResourceValidator,
)
from app.persistence.postgres.incident_unit_of_work import (
    PostgresHostedIncidentUnitOfWork,
)
from app.persistence.postgres.mappers import execution_intent_to_record
from app.persistence.postgres.models import AuditEventRecord, ExecutionIntentRecord
from app.persistence.postgres.tenant import TenantContext, tenant_transaction

from .conftest import PostgresTestDatabase
from .test_approval_persistence import (
    _approval_service,
    _completed_proposal,
    _seed_admin,
)
from .test_workspace_persistence import NOW


def _service(runtime_session_factory, *, clock=lambda: NOW + timedelta(minutes=2)):
    authorization = AuthorizationService(
        PostgresAuthorizationFactsRepository(runtime_session_factory),
        PostgresTenantResourceValidator(runtime_session_factory),
    )
    return HostedExecutionIntentService(
        authorization,
        lambda context: PostgresHostedIncidentUnitOfWork(
            runtime_session_factory, context
        ),
        clock=clock,
    )


def _approved(postgres_database, runtime_session_factory, suffix):
    requester, organization_id, workspace, proposal = _completed_proposal(
        postgres_database, runtime_session_factory, suffix=suffix
    )
    approver = _seed_admin(postgres_database, organization_id, suffix + 1000)
    approval = _approval_service(runtime_session_factory).request_approval(
        requester, organization_id, workspace.id, proposal.id
    )
    approval = _approval_service(
        runtime_session_factory, clock=lambda: NOW + timedelta(minutes=1)
    ).approve(approver, organization_id, workspace.id, approval.id)
    return requester, organization_id, workspace, proposal, approval


def test_concurrent_preparation_creates_one_immutable_intent(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    actor, organization_id, workspace, proposal, approval = _approved(
        postgres_database, runtime_session_factory, 240
    )
    service = _service(runtime_session_factory)

    def prepare_once(_):
        return service.prepare(actor, organization_id, workspace.id, approval.id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        intents = tuple(executor.map(prepare_once, range(2)))

    assert intents[0].id == intents[1].id
    assert intents[0].intent_hash == intents[1].intent_hash
    with tenant_transaction(
        runtime_session_factory, TenantContext(organization_id, workspace.id)
    ) as session:
        assert (
            session.scalar(select(func.count()).select_from(ExecutionIntentRecord)) == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEventRecord)
                .where(AuditEventRecord.event_type == "execution_intent.prepared")
            )
            == 1
        )

    with pytest.raises(DBAPIError, match="defining fields are immutable"):
        with postgres_database.migration_engine.begin() as connection:
            connection.execute(
                update(ExecutionIntentRecord)
                .where(ExecutionIntentRecord.id == UUID(str(intents[0].id)))
                .values(target_identifier="different-target")
            )


def test_intent_rls_and_tenant_fk_fail_closed(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    actor, organization_id, workspace, _, approval = _approved(
        postgres_database, runtime_session_factory, 241
    )
    intent = _service(runtime_session_factory).prepare(
        actor, organization_id, workspace.id, approval.id
    )

    with Session(postgres_database.runtime_engine) as session, session.begin():
        assert (
            session.scalar(select(func.count()).select_from(ExecutionIntentRecord)) == 0
        )

    _, other_org, other_workspace, _, other_approval = _approved(
        postgres_database, runtime_session_factory, 242
    )
    with tenant_transaction(
        runtime_session_factory, TenantContext(other_org, other_workspace.id)
    ) as session:
        assert (
            session.scalar(select(func.count()).select_from(ExecutionIntentRecord)) == 0
        )

    invalid = execution_intent_to_record(intent)
    invalid.id = uuid4()
    invalid.approval_id = UUID(str(other_approval.id))
    invalid.intent_hash = "d" * 64
    with pytest.raises(IntegrityError):
        with Session(postgres_database.migration_engine) as session, session.begin():
            session.add(invalid)


def test_terminal_intent_cannot_be_resurrected_by_direct_sql(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    actor, organization_id, workspace, _, approval = _approved(
        postgres_database, runtime_session_factory, 243
    )
    service = _service(runtime_session_factory)
    intent = service.prepare(actor, organization_id, workspace.id, approval.id)
    cancelled = service.cancel(
        actor,
        organization_id,
        workspace.id,
        intent.id,
        reason="Target no longer requires action",
    )

    with pytest.raises(ProgrammingError, match="lifecycle transition"):
        with postgres_database.migration_engine.begin() as connection:
            connection.execute(
                update(ExecutionIntentRecord)
                .where(ExecutionIntentRecord.id == UUID(str(cancelled.id)))
                .values(
                    lifecycle_state="prepared",
                    state_version=cancelled.state_version + 1,
                    terminal_at=None,
                    terminal_reason=None,
                )
            )
