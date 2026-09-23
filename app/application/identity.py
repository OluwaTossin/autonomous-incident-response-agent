"""Hosted identity application services; authentication without authorization."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol, Self

from app.auth.context import ActorContext, AuthenticationMethod
from app.auth.errors import AuthenticationFailed
from app.auth.oidc import OidcJwtVerifier, VerifiedHumanIdentity
from app.auth.service_credentials import (
    IssuedServiceAccountSecret,
    issue_service_account_secret,
    parse_service_account_credential,
    verify_service_account_secret,
)
from app.domain.common import ActorKind, ActorReference
from app.domain.identifiers import ServiceAccountCredentialId, ServiceAccountId, UserId
from app.domain.identity import ServiceAccount, ServiceAccountCredential
from app.domain.tenancy import User


class UserIdentityRepository(Protocol):
    def get_by_provider_subject(self, issuer: str, subject: str) -> User | None: ...

    def add(self, user: User) -> None: ...

    def save(self, user: User) -> None: ...


class ServiceAccountRepository(Protocol):
    def get(self, service_account_id: ServiceAccountId) -> ServiceAccount | None: ...

    def add(self, service_account: ServiceAccount) -> None: ...

    def save(self, service_account: ServiceAccount) -> None: ...


class ServiceAccountCredentialRepository(Protocol):
    def get_by_lookup_id(self, lookup_id: str) -> ServiceAccountCredential | None: ...

    def list_active(
        self, service_account_id: ServiceAccountId
    ) -> Sequence[ServiceAccountCredential]: ...

    def add(self, credential: ServiceAccountCredential) -> None: ...

    def save(self, credential: ServiceAccountCredential) -> None: ...


class IdentityUnitOfWork(Protocol):
    users: UserIdentityRepository
    service_accounts: ServiceAccountRepository
    service_account_credentials: ServiceAccountCredentialRepository

    def __enter__(self) -> Self: ...

    def __exit__(self, exc_type, exc_value, traceback) -> None: ...


IdentityUnitOfWorkFactory = Callable[[], IdentityUnitOfWork]


class IdentityConflict(Exception):
    """A durable provider or public credential identity already exists."""


class HumanAuthenticator:
    def __init__(
        self,
        verifier: OidcJwtVerifier,
        uow_factory: IdentityUnitOfWorkFactory,
        *,
        user_id_factory: Callable[[], UserId] = UserId.new,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._verifier = verifier
        self._uow_factory = uow_factory
        self._user_id_factory = user_id_factory
        self._clock = clock

    def authenticate(self, token: str, *, request_id: str | None = None) -> ActorContext:
        identity = self._verifier.verify(token)
        user = self._resolve_user(identity)
        return ActorContext(
            actor=ActorReference(ActorKind.HUMAN, actor_id=user.id),
            authentication_method=AuthenticationMethod.OIDC,
            issuer=identity.issuer,
            external_subject=identity.subject,
            request_id=request_id,
        )

    def _resolve_user(self, identity: VerifiedHumanIdentity) -> User:
        try:
            with self._uow_factory() as uow:
                user = uow.users.get_by_provider_subject(
                    identity.issuer, identity.subject
                )
                if user is None:
                    if not identity.email or not identity.display_name:
                        raise AuthenticationFailed("Authentication failed")
                    user = User(
                        id=self._user_id_factory(),
                        email=identity.email,
                        display_name=identity.display_name,
                        identity_provider=identity.issuer,
                        provider_subject=identity.subject,
                        created_at=self._clock(),
                    )
                    uow.users.add(user)
                elif user.disabled_at is not None:
                    raise AuthenticationFailed("Authentication failed")
                else:
                    updated = replace(
                        user,
                        email=identity.email or user.email,
                        display_name=identity.display_name or user.display_name,
                    )
                    if updated != user:
                        uow.users.save(updated)
                        user = updated
                return user
        except IdentityConflict as exc:
            raise AuthenticationFailed("Authentication failed") from exc


@dataclass(frozen=True, slots=True, repr=False)
class CreatedServiceAccount:
    service_account: ServiceAccount
    credential: str

    def __repr__(self) -> str:
        return (
            f"CreatedServiceAccount(service_account={self.service_account!r}, "
            "credential='<redacted>')"
        )


class ServiceAccountIdentityService:
    def __init__(
        self,
        uow_factory: IdentityUnitOfWorkFactory,
        *,
        account_id_factory: Callable[[], ServiceAccountId] = ServiceAccountId.new,
        credential_id_factory: Callable[[], ServiceAccountCredentialId] = (
            ServiceAccountCredentialId.new
        ),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory = uow_factory
        self._account_id_factory = account_id_factory
        self._credential_id_factory = credential_id_factory
        self._clock = clock

    def create(
        self,
        *,
        name: str,
        created_by: ActorReference,
        expires_at: datetime | None = None,
    ) -> CreatedServiceAccount:
        now = self._clock()
        account = ServiceAccount(
            id=self._account_id_factory(),
            name=name,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        issued = issue_service_account_secret()
        stored = self._stored_credential(
            account.id, issued, created_by, now, expires_at
        )
        with self._uow_factory() as uow:
            uow.service_accounts.add(account)
            uow.service_account_credentials.add(stored)
        return CreatedServiceAccount(account, issued.credential)

    def authenticate(
        self, credential: str, *, request_id: str | None = None
    ) -> ActorContext:
        lookup_id, secret = parse_service_account_credential(credential)
        now = self._clock()
        with self._uow_factory() as uow:
            stored = uow.service_account_credentials.get_by_lookup_id(lookup_id)
            if stored is None:
                verify_service_account_secret(secret, b"\0" * 16, b"\0" * 32)
                raise AuthenticationFailed("Authentication failed")
            account = uow.service_accounts.get(stored.service_account_id)
            secret_valid = verify_service_account_secret(
                secret, stored.salt, stored.verifier
            )
            if (
                account is None
                or account.disabled
                or stored.revoked
                or stored.is_expired(now)
                or not secret_valid
            ):
                raise AuthenticationFailed("Authentication failed")
            uow.service_account_credentials.save(replace(stored, last_used_at=now))
        return ActorContext(
            actor=ActorReference(ActorKind.SERVICE_ACCOUNT, actor_id=account.id),
            authentication_method=AuthenticationMethod.SERVICE_ACCOUNT,
            credential_id=stored.lookup_id,
            request_id=request_id,
        )

    def rotate(
        self,
        service_account_id: ServiceAccountId,
        *,
        rotated_by: ActorReference,
        expires_at: datetime | None = None,
    ) -> str:
        now = self._clock()
        issued = issue_service_account_secret()
        with self._uow_factory() as uow:
            account = uow.service_accounts.get(service_account_id)
            if account is None or account.disabled:
                raise AuthenticationFailed("Authentication failed")
            for current in uow.service_account_credentials.list_active(
                service_account_id
            ):
                uow.service_account_credentials.save(
                    replace(current, revoked_at=now, revoked_by=rotated_by)
                )
            uow.service_account_credentials.add(
                self._stored_credential(
                    service_account_id, issued, rotated_by, now, expires_at
                )
            )
        return issued.credential

    def revoke(
        self, service_account_id: ServiceAccountId, *, revoked_by: ActorReference
    ) -> None:
        now = self._clock()
        with self._uow_factory() as uow:
            account = uow.service_accounts.get(service_account_id)
            if account is None:
                raise AuthenticationFailed("Authentication failed")
            if not account.disabled:
                uow.service_accounts.save(account.disable(actor=revoked_by, at=now))

    def _stored_credential(
        self,
        service_account_id: ServiceAccountId,
        issued: IssuedServiceAccountSecret,
        created_by: ActorReference,
        created_at: datetime,
        expires_at: datetime | None,
    ) -> ServiceAccountCredential:
        return ServiceAccountCredential(
            id=self._credential_id_factory(),
            service_account_id=service_account_id,
            lookup_id=issued.lookup_id,
            verifier=issued.verifier,
            salt=issued.salt,
            algorithm=issued.algorithm,
            created_by=created_by,
            created_at=created_at,
            expires_at=expires_at,
        )
