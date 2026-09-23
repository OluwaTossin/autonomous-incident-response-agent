"""Real PostgreSQL identity persistence and authentication/RLS separation."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.identity import HumanAuthenticator, ServiceAccountIdentityService
from app.auth.errors import AuthenticationFailed
from app.auth.oidc import VerifiedHumanIdentity
from app.domain.common import ActorKind, ActorReference
from app.domain.identifiers import OrganizationId, UserId
from app.domain.tenancy import Organization, User
from app.persistence.postgres.identity_unit_of_work import PostgresIdentityUnitOfWork
from app.persistence.postgres.mappers import organization_to_record, user_to_record
from app.persistence.postgres.models import (
    OrganizationRecord,
    ServiceAccountRecord,
    ServiceAccountCredentialRecord,
    UserRecord,
)

from .conftest import PostgresTestDatabase

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
ISSUER = "https://cognito-idp.eu-west-2.amazonaws.com/eu-west-2_example"
USER_ID = UserId("00000000-0000-4000-8000-000000000901")
CREATOR = ActorReference(ActorKind.HUMAN, actor_id=USER_ID)


class StaticVerifier:
    def __init__(self, identity: VerifiedHumanIdentity) -> None:
        self.identity = identity

    def verify(self, _token: str) -> VerifiedHumanIdentity:
        return self.identity


def _uow_factory(runtime_session_factory):
    return lambda: PostgresIdentityUnitOfWork(runtime_session_factory)


def test_human_first_sign_in_returning_mapping_and_metadata_update(
    runtime_session_factory,
) -> None:
    identity = VerifiedHumanIdentity(
        ISSUER, "subject-1", "operator@example.com", "Operator"
    )
    authenticator = HumanAuthenticator(
        StaticVerifier(identity),
        _uow_factory(runtime_session_factory),
        user_id_factory=lambda: USER_ID,
        clock=lambda: NOW,
    )
    assert authenticator.authenticate("token").actor.actor_id == USER_ID

    changed = HumanAuthenticator(
        StaticVerifier(
            VerifiedHumanIdentity(
                ISSUER, "subject-1", "changed@example.com", "Changed"
            )
        ),
        _uow_factory(runtime_session_factory),
        clock=lambda: NOW,
    )
    assert changed.authenticate("token").actor.actor_id == USER_ID
    with runtime_session_factory.begin() as session:
        record = session.scalar(select(UserRecord))
        assert record.email == "changed@example.com"
        assert record.display_name == "Changed"


def test_disabled_user_and_provider_subject_collision_fail_closed(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    first = User(
        id=USER_ID,
        email="first@example.com",
        display_name="First",
        identity_provider=ISSUER,
        provider_subject="subject-1",
        created_at=NOW,
        disabled_at=NOW,
    )
    with runtime_session_factory.begin() as session:
        session.add(user_to_record(first))

    authenticator = HumanAuthenticator(
        StaticVerifier(
            VerifiedHumanIdentity(ISSUER, "subject-1", "first@example.com", "First")
        ),
        _uow_factory(runtime_session_factory),
    )
    with pytest.raises(AuthenticationFailed):
        authenticator.authenticate("token")

    duplicate = User(
        id=UserId("00000000-0000-4000-8000-000000000902"),
        email="second@example.com",
        display_name="Second",
        identity_provider=ISSUER,
        provider_subject="subject-1",
        created_at=NOW,
    )
    with pytest.raises(IntegrityError):
        with Session(postgres_database.migration_engine) as session, session.begin():
            session.add(user_to_record(duplicate))


def test_service_account_secret_lifecycle_persists_only_verifier(
    runtime_session_factory,
) -> None:
    service = ServiceAccountIdentityService(
        _uow_factory(runtime_session_factory), clock=lambda: NOW
    )
    created = service.create(name="CI integration", created_by=CREATOR)
    context = service.authenticate(created.credential)
    assert context.actor.kind is ActorKind.SERVICE_ACCOUNT

    lookup_id, raw_secret = created.credential.removeprefix("aira_sa_").split(".")
    with runtime_session_factory.begin() as session:
        credential = session.execute(
            select(
                func.encode(ServiceAccountCredentialRecord.verifier, "hex"),
                ServiceAccountCredentialRecord.lookup_id,
            )
        ).one()
        account = session.scalar(select(ServiceAccountRecord))
    assert credential[1] == lookup_id
    assert raw_secret not in credential[0]
    assert account.actor_kind == "human"
    assert account.actor_id == UUID(str(USER_ID))

    rotated = service.rotate(context.actor.actor_id, rotated_by=CREATOR)
    with pytest.raises(AuthenticationFailed):
        service.authenticate(created.credential)
    assert service.authenticate(rotated).actor.actor_id == context.actor.actor_id
    service.revoke(context.actor.actor_id, revoked_by=CREATOR)
    with pytest.raises(AuthenticationFailed):
        service.authenticate(rotated)
    with runtime_session_factory.begin() as session:
        account = session.scalar(select(ServiceAccountRecord))
        assert account.disabled_by_kind == "human"
        assert account.disabled_by_id == UUID(str(USER_ID))


def test_authenticated_identity_alone_cannot_read_tenant_rows(
    postgres_database: PostgresTestDatabase,
    runtime_session_factory,
) -> None:
    organization = Organization(
        id=OrganizationId("00000000-0000-4000-8000-000000000903"),
        name="Hidden tenant",
        slug="hidden-tenant",
        created_by=CREATOR,
        created_at=NOW,
        updated_at=NOW,
    )
    with Session(postgres_database.migration_engine) as session, session.begin():
        session.add(organization_to_record(organization))

    authenticator = HumanAuthenticator(
        StaticVerifier(
            VerifiedHumanIdentity(
                ISSUER, "subject-no-membership", "new@example.com", "New"
            )
        ),
        _uow_factory(runtime_session_factory),
        user_id_factory=lambda: USER_ID,
        clock=lambda: NOW,
    )
    actor = authenticator.authenticate("token")
    assert actor.actor.actor_id == USER_ID

    with runtime_session_factory.begin() as session:
        assert session.scalar(select(func.count()).select_from(OrganizationRecord)) == 0
