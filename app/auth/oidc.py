"""Cognito-compatible OIDC JWT verification with bounded JWKS caching."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx
import jwt

from app.auth.errors import AuthenticationFailed, IdentityConfigurationError


@dataclass(frozen=True, slots=True)
class OidcVerifierConfig:
    issuer: str
    client_id: str
    token_use: str = "access"
    jwks_url: str | None = None
    allowed_algorithms: tuple[str, ...] = ("RS256",)
    leeway_seconds: int = 30
    jwks_cache_seconds: int = 300
    http_timeout_seconds: float = 3.0

    def __post_init__(self) -> None:
        issuer = self.issuer.rstrip("/")
        if urlparse(issuer).scheme != "https":
            raise IdentityConfigurationError("OIDC issuer must use HTTPS")
        if len(issuer) > 255:
            raise IdentityConfigurationError("OIDC issuer is too long")
        object.__setattr__(self, "issuer", issuer)
        if not self.client_id.strip():
            raise IdentityConfigurationError("OIDC client ID is required")
        if self.token_use not in {"access", "id"}:
            raise IdentityConfigurationError("OIDC token_use must be access or id")
        if not self.allowed_algorithms or any(
            algorithm not in {"RS256", "RS384", "RS512"}
            for algorithm in self.allowed_algorithms
        ):
            raise IdentityConfigurationError("Only explicit RSA JWT algorithms are supported")
        if self.leeway_seconds < 0 or self.jwks_cache_seconds <= 0:
            raise IdentityConfigurationError("OIDC cache and clock values must be positive")
        if self.http_timeout_seconds <= 0:
            raise IdentityConfigurationError("OIDC HTTP timeout must be positive")
        url = self.jwks_url or f"{issuer}/.well-known/jwks.json"
        if urlparse(url).scheme != "https":
            raise IdentityConfigurationError("JWKS URL must use HTTPS")
        object.__setattr__(self, "jwks_url", url)


@dataclass(frozen=True, slots=True)
class VerifiedHumanIdentity:
    issuer: str
    subject: str
    email: str | None = None
    display_name: str | None = None


class SigningKeyProvider(Protocol):
    def get_signing_key(self, key_id: str) -> Any: ...


class CachingJwksProvider:
    """Fetch and cache signing keys; stale caches are never used beyond their TTL."""

    def __init__(
        self,
        config: OidcVerifierConfig,
        *,
        client: httpx.Client | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._client = client or httpx.Client(timeout=config.http_timeout_seconds)
        self._monotonic = monotonic
        self._keys: dict[str, Any] = {}
        self._expires_at = 0.0
        self._lock = threading.Lock()

    def get_signing_key(self, key_id: str) -> Any:
        if not key_id:
            raise AuthenticationFailed("Authentication failed")
        with self._lock:
            now = self._monotonic()
            refreshed = False
            if now >= self._expires_at:
                self._refresh(now)
                refreshed = True
            key = self._keys.get(key_id)
            if key is None and not refreshed:
                self._refresh(now)
                key = self._keys.get(key_id)
            if key is None:
                raise AuthenticationFailed("Authentication failed")
            return key

    def _refresh(self, now: float) -> None:
        try:
            response = self._client.get(str(self._config.jwks_url))
            response.raise_for_status()
            payload = response.json()
            raw_keys = payload.get("keys") if isinstance(payload, dict) else None
            if not isinstance(raw_keys, list):
                raise ValueError("JWKS payload has no keys")
            keys = {
                str(item["kid"]): jwt.PyJWK.from_dict(item).key
                for item in raw_keys
                if isinstance(item, dict) and item.get("kid")
            }
            if not keys:
                raise ValueError("JWKS payload has no usable keys")
        except (httpx.HTTPError, ValueError, TypeError, jwt.PyJWTError) as exc:
            raise AuthenticationFailed("Authentication failed") from exc
        self._keys = keys
        self._expires_at = now + self._config.jwks_cache_seconds


class OidcJwtVerifier:
    def __init__(
        self,
        config: OidcVerifierConfig,
        key_provider: SigningKeyProvider | None = None,
    ) -> None:
        self._config = config
        self._key_provider = key_provider or CachingJwksProvider(config)

    def verify(self, token: str) -> VerifiedHumanIdentity:
        try:
            header = jwt.get_unverified_header(token)
            key_id = header.get("kid")
            algorithm = header.get("alg")
            if not isinstance(key_id, str) or algorithm not in self._config.allowed_algorithms:
                raise AuthenticationFailed("Authentication failed")
            key = self._key_provider.get_signing_key(key_id)
            options = {
                "require": ["exp", "iss", "sub", "token_use"],
                "verify_aud": self._config.token_use == "id",
            }
            claims: Mapping[str, Any] = jwt.decode(
                token,
                key=key,
                algorithms=list(self._config.allowed_algorithms),
                audience=(
                    self._config.client_id if self._config.token_use == "id" else None
                ),
                issuer=self._config.issuer,
                leeway=self._config.leeway_seconds,
                options=options,
            )
            if claims.get("token_use") != self._config.token_use:
                raise AuthenticationFailed("Authentication failed")
            if (
                self._config.token_use == "access"
                and claims.get("client_id") != self._config.client_id
            ):
                raise AuthenticationFailed("Authentication failed")
            subject = claims.get("sub")
            if (
                not isinstance(subject, str)
                or not subject.strip()
                or len(subject) > 255
            ):
                raise AuthenticationFailed("Authentication failed")
            return VerifiedHumanIdentity(
                issuer=self._config.issuer,
                subject=subject.strip(),
                email=_optional_string(claims.get("email"), max_length=320),
                display_name=_optional_string(
                    claims.get("name") or claims.get("cognito:username"),
                    max_length=200,
                ),
            )
        except AuthenticationFailed:
            raise
        except (jwt.PyJWTError, ValueError, TypeError) as exc:
            raise AuthenticationFailed("Authentication failed") from exc


def _optional_string(value: Any, *, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized and len(normalized) <= max_length else None
