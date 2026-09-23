"""Explicit hosted identity composition, separate from Version 2 API-key auth."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from app.api.hosted_auth import HostedActorDependency
from app.application.identity import HumanAuthenticator, ServiceAccountIdentityService
from app.auth.oidc import OidcJwtVerifier, OidcVerifierConfig
from app.config.settings import Settings
from app.persistence.postgres.identity_unit_of_work import PostgresIdentityUnitOfWork


def build_hosted_actor_dependency(
    settings: Settings,
    session_factory: sessionmaker[Session],
) -> HostedActorDependency:
    """Build hosted authentication only when the hosted composition requests it."""
    config = OidcVerifierConfig(
        issuer=settings.aira_oidc_issuer,
        client_id=settings.aira_oidc_client_id,
        token_use=settings.aira_oidc_token_use,
        jwks_url=settings.aira_oidc_jwks_url or None,
        allowed_algorithms=tuple(
            algorithm.strip()
            for algorithm in settings.aira_oidc_algorithms.split(",")
            if algorithm.strip()
        ),
        leeway_seconds=settings.aira_oidc_leeway_seconds,
        jwks_cache_seconds=settings.aira_oidc_jwks_cache_seconds,
        http_timeout_seconds=settings.aira_oidc_http_timeout_seconds,
    )
    def uow_factory() -> PostgresIdentityUnitOfWork:
        return PostgresIdentityUnitOfWork(session_factory)

    return HostedActorDependency(
        HumanAuthenticator(OidcJwtVerifier(config), uow_factory),
        ServiceAccountIdentityService(uow_factory),
    )
