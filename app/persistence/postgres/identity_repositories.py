"""Global PostgreSQL identity repositories used before tenant authorization."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.identifiers import ServiceAccountId
from app.domain.identity import ServiceAccount, ServiceAccountCredential
from app.domain.tenancy import User
from app.application.identity import IdentityConflict
from app.persistence.postgres.mappers import (
    service_account_credential_from_record,
    service_account_credential_to_record,
    service_account_from_record,
    service_account_to_record,
    user_from_record,
    user_to_record,
)
from app.persistence.postgres.models import (
    ServiceAccountCredentialRecord,
    ServiceAccountRecord,
    UserRecord,
)


class PostgresUserIdentityRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_provider_subject(self, issuer: str, subject: str) -> User | None:
        record = self._session.scalar(
            select(UserRecord).where(
                UserRecord.identity_provider == issuer,
                UserRecord.provider_subject == subject,
            )
        )
        return user_from_record(record) if record else None

    def add(self, user: User) -> None:
        try:
            self._session.add(user_to_record(user))
            self._session.flush()
        except IntegrityError as exc:
            raise IdentityConflict("Provider identity already exists") from exc

    def save(self, user: User) -> None:
        self._session.merge(user_to_record(user))
        self._session.flush()


class PostgresServiceAccountRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, service_account_id: ServiceAccountId) -> ServiceAccount | None:
        record = self._session.get(
            ServiceAccountRecord, UUID(str(service_account_id))
        )
        return service_account_from_record(record) if record else None

    def add(self, service_account: ServiceAccount) -> None:
        try:
            self._session.add(service_account_to_record(service_account))
            self._session.flush()
        except IntegrityError as exc:
            raise IdentityConflict("Service account identity already exists") from exc

    def save(self, service_account: ServiceAccount) -> None:
        self._session.merge(service_account_to_record(service_account))
        self._session.flush()


class PostgresServiceAccountCredentialRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_lookup_id(self, lookup_id: str) -> ServiceAccountCredential | None:
        record = self._session.scalar(
            select(ServiceAccountCredentialRecord).where(
                ServiceAccountCredentialRecord.lookup_id == lookup_id
            )
        )
        return service_account_credential_from_record(record) if record else None

    def list_active(
        self, service_account_id: ServiceAccountId
    ) -> list[ServiceAccountCredential]:
        records = self._session.scalars(
            select(ServiceAccountCredentialRecord).where(
                ServiceAccountCredentialRecord.service_account_id
                == UUID(str(service_account_id)),
                ServiceAccountCredentialRecord.revoked_at.is_(None),
            )
        ).all()
        return [service_account_credential_from_record(record) for record in records]

    def add(self, credential: ServiceAccountCredential) -> None:
        try:
            self._session.add(service_account_credential_to_record(credential))
            self._session.flush()
        except IntegrityError as exc:
            raise IdentityConflict("Credential identity already exists") from exc

    def save(self, credential: ServiceAccountCredential) -> None:
        self._session.merge(service_account_credential_to_record(credential))
        self._session.flush()
