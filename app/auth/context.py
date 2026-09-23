"""Verified actor identity without tenant authorization or secrets."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.domain.common import ActorKind, ActorReference, DomainInvariantError


class AuthenticationMethod(StrEnum):
    OIDC = "oidc"
    SERVICE_ACCOUNT = "service_account"
    WORKLOAD_IDENTITY = "workload_identity"


@dataclass(frozen=True, slots=True, repr=False)
class ActorContext:
    """Request/job-scoped authenticated identity; never an authorization decision."""

    actor: ActorReference
    authentication_method: AuthenticationMethod
    issuer: str | None = None
    external_subject: str | None = None
    credential_id: str | None = None
    request_id: str | None = None

    def __post_init__(self) -> None:
        if self.authentication_method is AuthenticationMethod.OIDC:
            if self.actor.kind is not ActorKind.HUMAN:
                raise DomainInvariantError("OIDC authentication requires a human actor")
            if not self.issuer or not self.external_subject:
                raise DomainInvariantError("OIDC actors require issuer and subject")
        elif self.authentication_method is AuthenticationMethod.SERVICE_ACCOUNT:
            if self.actor.kind is not ActorKind.SERVICE_ACCOUNT:
                raise DomainInvariantError(
                    "Service-account authentication requires a service-account actor"
                )
            if not self.credential_id:
                raise DomainInvariantError(
                    "Service-account actors require a credential identifier"
                )
        elif self.authentication_method is AuthenticationMethod.WORKLOAD_IDENTITY:
            if self.actor.kind is not ActorKind.SYSTEM:
                raise DomainInvariantError(
                    "Workload identity authentication requires a system actor"
                )
            if not self.issuer or not self.external_subject:
                raise DomainInvariantError(
                    "Workload identity actors require issuer and subject"
                )

        for name in ("issuer", "external_subject", "credential_id", "request_id"):
            value = getattr(self, name)
            if value is not None:
                normalized = value.strip()
                if not normalized or len(normalized) > 512 or any(
                    char in normalized for char in "\r\n"
                ):
                    raise DomainInvariantError(f"ActorContext {name} is invalid")
                object.__setattr__(self, name, normalized)

    def safe_log_fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "actor_kind": self.actor.kind.value,
            "actor_id": str(self.actor.actor_id) if self.actor.actor_id else None,
            "system_name": self.actor.system_name,
            "authentication_method": self.authentication_method.value,
        }
        if self.request_id:
            fields["request_id"] = self.request_id
        return fields

    def __repr__(self) -> str:
        return f"ActorContext({self.safe_log_fields()!r})"


def trusted_system_actor(
    *,
    system_name: str,
    workload_issuer: str,
    workload_subject: str,
    request_id: str | None = None,
) -> ActorContext:
    """Construct a system actor only after trusted composition verifies workload identity."""
    return ActorContext(
        actor=ActorReference(ActorKind.SYSTEM, system_name=system_name),
        authentication_method=AuthenticationMethod.WORKLOAD_IDENTITY,
        issuer=workload_issuer,
        external_subject=workload_subject,
        request_id=request_id,
    )
