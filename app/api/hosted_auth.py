"""Reusable FastAPI authentication dependency for future hosted routes."""

from __future__ import annotations

from typing import Protocol

from fastapi import HTTPException, Request

from app.auth.context import ActorContext
from app.auth.errors import AuthenticationFailed


class HumanRequestAuthenticator(Protocol):
    def authenticate(
        self,
        token: str,
        *,
        request_id: str | None = None,
        identity_token: str | None = None,
    ) -> ActorContext: ...


class MachineRequestAuthenticator(Protocol):
    def authenticate(
        self, credential: str, *, request_id: str | None = None
    ) -> ActorContext: ...


class HostedActorDependency:
    """Authenticate identity only; V3.5 must authorize tenant scope separately."""

    def __init__(
        self,
        human_authenticator: HumanRequestAuthenticator,
        service_account_authenticator: MachineRequestAuthenticator,
    ) -> None:
        self._human = human_authenticator
        self._service_account = service_account_authenticator

    def __call__(self, request: Request) -> ActorContext:
        authorization = request.headers.get("authorization", "")
        scheme, separator, credential = authorization.partition(" ")
        request_id = _safe_request_id(
            getattr(request.state, "correlation_id", None)
            or request.headers.get("x-correlation-id")
            or request.headers.get("x-request-id")
        )
        try:
            if not separator or not credential:
                raise AuthenticationFailed("Authentication failed")
            if scheme.lower() == "bearer":
                identity_token = request.headers.get("x-aira-id-token")
                if identity_token:
                    return self._human.authenticate(
                        credential,
                        request_id=request_id,
                        identity_token=identity_token,
                    )
                return self._human.authenticate(credential, request_id=request_id)
            if scheme.lower() == "airaserviceaccount":
                return self._service_account.authenticate(
                    credential, request_id=request_id
                )
            raise AuthenticationFailed("Authentication failed")
        except AuthenticationFailed as exc:
            raise HTTPException(
                status_code=401,
                detail="Unauthorized",
                headers={"WWW-Authenticate": "Bearer, AiraServiceAccount"},
            ) from exc


def _safe_request_id(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > 128:
        return None
    return normalized
