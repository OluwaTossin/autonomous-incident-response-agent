"""Framework-independent hosted machine-identity records."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from app.domain.common import ActorReference, DomainInvariantError, require_aware
from app.domain.identifiers import ServiceAccountCredentialId, ServiceAccountId


@dataclass(frozen=True, slots=True)
class ServiceAccount:
    id: ServiceAccountId
    name: str
    created_by: ActorReference
    created_at: datetime
    updated_at: datetime
    disabled_at: datetime | None = None
    disabled_by: ActorReference | None = None

    def __post_init__(self) -> None:
        name = self.name.strip()
        if not name:
            raise DomainInvariantError("Service account name cannot be blank")
        object.__setattr__(self, "name", name)
        require_aware(self.created_at, "created_at")
        require_aware(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise DomainInvariantError("updated_at cannot precede created_at")
        if self.disabled_at is not None:
            require_aware(self.disabled_at, "disabled_at")
            if self.disabled_at < self.created_at:
                raise DomainInvariantError("disabled_at cannot precede created_at")
        if (self.disabled_at is None) != (self.disabled_by is None):
            raise DomainInvariantError("disabled_at and disabled_by must be set together")

    @property
    def disabled(self) -> bool:
        return self.disabled_at is not None

    def disable(self, *, actor: ActorReference, at: datetime) -> ServiceAccount:
        if self.disabled:
            raise DomainInvariantError("Service account is already disabled")
        return replace(self, disabled_at=at, disabled_by=actor, updated_at=at)


@dataclass(frozen=True, slots=True, repr=False)
class ServiceAccountCredential:
    id: ServiceAccountCredentialId
    service_account_id: ServiceAccountId
    lookup_id: str
    verifier: bytes
    salt: bytes
    algorithm: str
    created_by: ActorReference
    created_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    revoked_by: ActorReference | None = None
    last_used_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.lookup_id.strip():
            raise DomainInvariantError("Credential lookup_id cannot be blank")
        if not self.verifier or not self.salt:
            raise DomainInvariantError("Credential verifier and salt are required")
        if self.algorithm != "scrypt-v1":
            raise DomainInvariantError("Unsupported credential verifier algorithm")
        require_aware(self.created_at, "created_at")
        for name, value in (
            ("expires_at", self.expires_at),
            ("revoked_at", self.revoked_at),
            ("last_used_at", self.last_used_at),
        ):
            if value is not None:
                require_aware(value, name)
        if self.expires_at is not None and self.expires_at <= self.created_at:
            raise DomainInvariantError("expires_at must follow created_at")
        if (self.revoked_at is None) != (self.revoked_by is None):
            raise DomainInvariantError("revoked_at and revoked_by must be set together")

    @property
    def revoked(self) -> bool:
        return self.revoked_at is not None

    def is_expired(self, at: datetime) -> bool:
        return self.expires_at is not None and self.expires_at <= at

    def __repr__(self) -> str:
        return (
            "ServiceAccountCredential("
            f"id={self.id!r}, service_account_id={self.service_account_id!r}, "
            f"lookup_id={self.lookup_id!r}, verifier='<redacted>', salt='<redacted>', "
            f"algorithm={self.algorithm!r}, created_by={self.created_by!r}, "
            f"created_at={self.created_at!r}, "
            f"expires_at={self.expires_at!r}, revoked_at={self.revoked_at!r}, "
            f"revoked_by={self.revoked_by!r}, last_used_at={self.last_used_at!r})"
        )
