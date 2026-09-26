"""ActorContext, identity mapping, and service-account lifecycle tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import count

import pytest

from app.application.identity import HumanAuthenticator, ServiceAccountIdentityService
from app.auth.context import ActorContext, AuthenticationMethod, trusted_system_actor
from app.auth.errors import AuthenticationFailed
from app.auth.oidc import VerifiedHumanIdentity
from app.domain.common import ActorKind, ActorReference
from app.domain.identifiers import (
    ServiceAccountCredentialId,
    ServiceAccountId,
    UserId,
)
from app.domain.tenancy import User

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
ISSUER = "https://cognito-idp.eu-west-2.amazonaws.com/eu-west-2_example"
USER_ID = UserId("00000000-0000-4000-8000-000000000001")
ACCOUNT_ID = ServiceAccountId("00000000-0000-4000-8000-000000000002")
CREATOR = ActorReference(ActorKind.HUMAN, actor_id=USER_ID)


class FakeVerifier:
    def __init__(self, identity: VerifiedHumanIdentity) -> None:
        self.identity = identity

    def verify(self, _token: str) -> VerifiedHumanIdentity:
        return self.identity


class UserRepository:
    def __init__(self) -> None:
        self.by_identity: dict[tuple[str, str], User] = {}

    def get_by_provider_subject(self, issuer: str, subject: str) -> User | None:
        return self.by_identity.get((issuer, subject))

    def add(self, user: User) -> None:
        key = (user.identity_provider, user.provider_subject)
        if key in self.by_identity:
            raise RuntimeError("identity collision")
        self.by_identity[key] = user

    def save(self, user: User) -> None:
        self.by_identity[(user.identity_provider, user.provider_subject)] = user


class ServiceAccountRepository:
    def __init__(self) -> None:
        self.accounts = {}

    def get(self, service_account_id):
        return self.accounts.get(service_account_id)

    def add(self, account) -> None:
        self.accounts[account.id] = account

    def save(self, account) -> None:
        self.accounts[account.id] = account


class CredentialRepository:
    def __init__(self) -> None:
        self.credentials = {}

    def get_by_lookup_id(self, lookup_id):
        return self.credentials.get(lookup_id)

    def list_active(self, service_account_id):
        return [
            credential
            for credential in self.credentials.values()
            if credential.service_account_id == service_account_id
            and not credential.revoked
        ]

    def add(self, credential) -> None:
        self.credentials[credential.lookup_id] = credential

    def save(self, credential) -> None:
        self.credentials[credential.lookup_id] = credential


class MemoryIdentityStore:
    def __init__(self) -> None:
        self.users = UserRepository()
        self.service_accounts = ServiceAccountRepository()
        self.service_account_credentials = CredentialRepository()

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


def _human_authenticator(store, **overrides) -> HumanAuthenticator:
    identity = VerifiedHumanIdentity(
        issuer=ISSUER,
        subject="subject-1",
        email="operator@example.com",
        display_name="Operator",
    )
    identity = replace(identity, **overrides)
    return HumanAuthenticator(
        FakeVerifier(identity),
        store,
        user_id_factory=lambda: USER_ID,
        clock=lambda: NOW,
    )


def _service(store, now: datetime = NOW) -> ServiceAccountIdentityService:
    identifiers = count(3)
    return ServiceAccountIdentityService(
        store,
        account_id_factory=lambda: ACCOUNT_ID,
        credential_id_factory=lambda: ServiceAccountCredentialId(
            f"00000000-0000-4000-8000-{next(identifiers):012d}"
        ),
        clock=lambda: now,
    )


def test_first_sign_in_provisions_by_issuer_and_subject() -> None:
    store = MemoryIdentityStore()
    context = _human_authenticator(store).authenticate("verified-elsewhere")
    user = store.users.by_identity[(ISSUER, "subject-1")]
    assert user.id == USER_ID
    assert context.actor == ActorReference(ActorKind.HUMAN, actor_id=USER_ID)
    assert context.safe_log_fields()["authentication_method"] == "oidc"
    assert "subject-1" not in repr(context)


def test_first_sign_in_can_bind_verified_access_and_identity_tokens() -> None:
    store = MemoryIdentityStore()
    access = VerifiedHumanIdentity(ISSUER, "subject-1")
    identity = VerifiedHumanIdentity(
        ISSUER, "subject-1", "operator@example.com", "Operator"
    )
    authenticator = HumanAuthenticator(
        FakeVerifier(access),
        store,
        identity_verifier=FakeVerifier(identity),
        user_id_factory=lambda: USER_ID,
        clock=lambda: NOW,
    )
    context = authenticator.authenticate("access", identity_token="identity")
    assert context.actor.actor_id == USER_ID
    assert store.users.by_identity[(ISSUER, "subject-1")].email == "operator@example.com"


def test_identity_token_must_bind_to_access_token_subject() -> None:
    store = MemoryIdentityStore()
    authenticator = HumanAuthenticator(
        FakeVerifier(VerifiedHumanIdentity(ISSUER, "subject-1")),
        store,
        identity_verifier=FakeVerifier(
            VerifiedHumanIdentity(ISSUER, "subject-2", "x@example.com", "X")
        ),
    )
    with pytest.raises(AuthenticationFailed):
        authenticator.authenticate("access", identity_token="identity")


def test_returning_user_is_reused_and_profile_metadata_changes() -> None:
    store = MemoryIdentityStore()
    _human_authenticator(store).authenticate("token")
    context = _human_authenticator(
        store, email="new@example.com", display_name="New Name"
    ).authenticate("token")
    user = store.users.by_identity[(ISSUER, "subject-1")]
    assert user.email == "new@example.com"
    assert user.display_name == "New Name"
    assert context.actor.actor_id == USER_ID
    assert len(store.users.by_identity) == 1


def test_email_does_not_link_a_different_provider_subject() -> None:
    store = MemoryIdentityStore()
    _human_authenticator(store).authenticate("token")
    second_id = UserId("00000000-0000-4000-8000-000000000099")
    authenticator = HumanAuthenticator(
        FakeVerifier(
            VerifiedHumanIdentity(
                ISSUER, "subject-2", "operator@example.com", "Operator"
            )
        ),
        store,
        user_id_factory=lambda: second_id,
        clock=lambda: NOW,
    )
    assert authenticator.authenticate("token").actor.actor_id == second_id
    assert len(store.users.by_identity) == 2


def test_disabled_user_and_incomplete_first_sign_in_fail_closed() -> None:
    store = MemoryIdentityStore()
    _human_authenticator(store).authenticate("token")
    user = store.users.by_identity[(ISSUER, "subject-1")]
    store.users.save(replace(user, disabled_at=NOW))
    with pytest.raises(AuthenticationFailed):
        _human_authenticator(store).authenticate("token")

    empty_store = MemoryIdentityStore()
    with pytest.raises(AuthenticationFailed):
        _human_authenticator(empty_store, email=None).authenticate("token")


def test_actor_context_variants_are_immutable_and_safe_to_log() -> None:
    human = ActorContext(
        actor=CREATOR,
        authentication_method=AuthenticationMethod.OIDC,
        issuer=ISSUER,
        external_subject="sensitive-subject",
    )
    system = trusted_system_actor(
        system_name="triage-worker",
        workload_issuer="aws-iam",
        workload_subject="role/session",
    )
    assert human.actor.kind is ActorKind.HUMAN
    assert system.actor.kind is ActorKind.SYSTEM
    assert "sensitive-subject" not in repr(human)
    assert "role/session" not in repr(system)
    with pytest.raises((AttributeError, TypeError)):
        human.issuer = "changed"  # type: ignore[misc]


def test_service_account_valid_wrong_malformed_and_plaintext_not_persisted() -> None:
    store = MemoryIdentityStore()
    service = _service(store)
    created = service.create(name="Automation", created_by=CREATOR)
    stored = next(iter(store.service_account_credentials.credentials.values()))

    context = service.authenticate(created.credential)
    assert context.actor.actor_id == ACCOUNT_ID
    assert context.actor.kind is ActorKind.SERVICE_ACCOUNT
    assert created.credential.encode() not in stored.verifier
    assert created.credential not in repr(created)
    assert created.credential not in repr(stored)

    with pytest.raises(AuthenticationFailed):
        service.authenticate("malformed")
    prefix, _secret = created.credential.rsplit(".", 1)
    with pytest.raises(AuthenticationFailed):
        service.authenticate(f"{prefix}.{'A' * 43}")


def test_service_account_rotation_revocation_and_expiry() -> None:
    store = MemoryIdentityStore()
    service = _service(store)
    created = service.create(name="Automation", created_by=CREATOR)
    rotated = service.rotate(ACCOUNT_ID, rotated_by=CREATOR)

    with pytest.raises(AuthenticationFailed):
        service.authenticate(created.credential)
    assert service.authenticate(rotated).actor.actor_id == ACCOUNT_ID

    service.revoke(ACCOUNT_ID, revoked_by=CREATOR)
    with pytest.raises(AuthenticationFailed):
        service.authenticate(rotated)

    expired_store = MemoryIdentityStore()
    expired_service = _service(expired_store)
    expired = expired_service.create(
        name="Expired",
        created_by=CREATOR,
        expires_at=NOW + timedelta(seconds=1),
    )
    later_service = _service(expired_store, NOW + timedelta(seconds=2))
    with pytest.raises(AuthenticationFailed):
        later_service.authenticate(expired.credential)
