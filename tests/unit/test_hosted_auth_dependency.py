"""FastAPI hosted authentication seam without attaching hosted routes."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api.hosted_auth import HostedActorDependency
from app.auth.context import ActorContext, AuthenticationMethod
from app.auth.errors import AuthenticationFailed
from app.domain.common import ActorKind, ActorReference
from app.domain.identifiers import ServiceAccountId, UserId

HUMAN = ActorContext(
    actor=ActorReference(
        ActorKind.HUMAN,
        actor_id=UserId("00000000-0000-4000-8000-000000000001"),
    ),
    authentication_method=AuthenticationMethod.OIDC,
    issuer="https://issuer.example.com",
    external_subject="subject",
)
MACHINE = ActorContext(
    actor=ActorReference(
        ActorKind.SERVICE_ACCOUNT,
        actor_id=ServiceAccountId("00000000-0000-4000-8000-000000000002"),
    ),
    authentication_method=AuthenticationMethod.SERVICE_ACCOUNT,
    credential_id="public-credential",
)


class Authenticator:
    def __init__(self, expected: str, result: ActorContext) -> None:
        self.expected = expected
        self.result = result

    def authenticate(self, credential: str, *, request_id=None) -> ActorContext:
        if credential != self.expected:
            raise AuthenticationFailed("Authentication failed")
        return self.result


def _request(authorization: str):
    request = MagicMock()
    request.headers = {"authorization": authorization}
    return request


def test_dependency_authenticates_human_and_service_account_schemes() -> None:
    dependency = HostedActorDependency(
        Authenticator("human-token", HUMAN),
        Authenticator("machine-secret", MACHINE),
    )
    assert dependency(_request("Bearer human-token")) is HUMAN
    assert dependency(_request("AiraServiceAccount machine-secret")) is MACHINE


@pytest.mark.parametrize(
    "authorization",
    ["", "Basic value", "Bearer wrong", "System caller-selected"],
)
def test_dependency_rejects_missing_invalid_and_caller_selected_system_identity(
    authorization: str,
) -> None:
    dependency = HostedActorDependency(
        Authenticator("human-token", HUMAN),
        Authenticator("machine-secret", MACHINE),
    )
    with pytest.raises(HTTPException) as error:
        dependency(_request(authorization))
    assert error.value.status_code == 401
    assert error.value.detail == "Unauthorized"


def test_actor_context_contains_no_tenant_or_role_authorization() -> None:
    assert not hasattr(HUMAN, "organization_id")
    assert not hasattr(HUMAN, "workspace_id")
    assert not hasattr(HUMAN, "role")
