"""Local JWT/JWKS verification tests; no live identity provider required."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth.errors import AuthenticationFailed
from app.auth.oidc import CachingJwksProvider, OidcJwtVerifier, OidcVerifierConfig

ISSUER = "https://cognito-idp.eu-west-2.amazonaws.com/eu-west-2_example"
CLIENT_ID = "client-123"
NOW = datetime.now(UTC)


def _key_pair(kid: str):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return private_key, jwk


KEY_ONE, JWK_ONE = _key_pair("key-one")
KEY_TWO, JWK_TWO = _key_pair("key-two")


class StaticKeys:
    def __init__(self, keys: dict[str, object]) -> None:
        self.keys = keys

    def get_signing_key(self, key_id: str):
        try:
            return self.keys[key_id]
        except KeyError as exc:
            raise AuthenticationFailed("Authentication failed") from exc


def _config(**overrides) -> OidcVerifierConfig:
    values = {
        "issuer": ISSUER,
        "client_id": CLIENT_ID,
        "leeway_seconds": 0,
    }
    values.update(overrides)
    return OidcVerifierConfig(**values)


def _claims(**overrides):
    claims = {
        "iss": ISSUER,
        "sub": "provider-subject",
        "client_id": CLIENT_ID,
        "token_use": "access",
        "exp": NOW + timedelta(minutes=5),
        "iat": NOW,
        "email": "operator@example.com",
        "name": "Operator",
    }
    claims.update(overrides)
    return claims


def _token(
    *,
    private_key=KEY_ONE,
    kid: str = "key-one",
    claims=None,
) -> str:
    return jwt.encode(
        claims or _claims(),
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )


def _verifier() -> OidcJwtVerifier:
    return OidcJwtVerifier(
        _config(),
        StaticKeys(
            {
                "key-one": KEY_ONE.public_key(),
                "key-two": KEY_TWO.public_key(),
            }
        ),
    )


def test_valid_access_token_returns_stable_provider_identity() -> None:
    identity = _verifier().verify(_token())
    assert identity.issuer == ISSUER
    assert identity.subject == "provider-subject"
    assert identity.email == "operator@example.com"
    assert identity.display_name == "Operator"


@pytest.mark.parametrize(
    "token",
    [
        _token(private_key=KEY_TWO, kid="key-one"),
        _token(claims=_claims(exp=NOW - timedelta(seconds=1))),
        _token(claims=_claims(nbf=NOW + timedelta(minutes=1))),
        _token(claims=_claims(iss="https://issuer.invalid")),
        _token(claims=_claims(client_id="wrong-client")),
        _token(claims=_claims(token_use="id", aud=CLIENT_ID)),
        _token(claims={key: value for key, value in _claims().items() if key != "sub"}),
        "not-a-jwt",
    ],
    ids=[
        "invalid-signature",
        "expired",
        "not-yet-valid",
        "wrong-issuer",
        "wrong-client",
        "wrong-token-use",
        "missing-subject",
        "malformed",
    ],
)
def test_invalid_tokens_fail_closed(token: str) -> None:
    with pytest.raises(AuthenticationFailed, match="Authentication failed"):
        _verifier().verify(token)


def test_unknown_kid_fails_closed() -> None:
    with pytest.raises(AuthenticationFailed):
        OidcJwtVerifier(
            _config(), StaticKeys({"key-one": KEY_ONE.public_key()})
        ).verify(_token(private_key=KEY_TWO, kid="unknown"))


def test_unknown_kid_triggers_one_successful_jwks_rotation_refresh() -> None:
    responses = iter(
        [
            httpx.Response(200, json={"keys": [JWK_ONE]}),
            httpx.Response(200, json={"keys": [JWK_ONE, JWK_TWO]}),
        ]
    )
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return next(responses)

    config = _config()
    provider = CachingJwksProvider(
        config,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    verifier = OidcJwtVerifier(config, provider)

    verifier.verify(_token())
    verifier.verify(_token(private_key=KEY_TWO, kid="key-two"))
    assert calls == 2


def test_unknown_kid_refresh_failure_fails_closed() -> None:
    responses = iter(
        [
            httpx.Response(200, json={"keys": [JWK_ONE]}),
            httpx.Response(503),
        ]
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return next(responses)

    config = _config()
    verifier = OidcJwtVerifier(
        config,
        CachingJwksProvider(
            config,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        ),
    )
    verifier.verify(_token())

    with pytest.raises(AuthenticationFailed):
        verifier.verify(_token(private_key=KEY_TWO, kid="key-two"))


def test_expired_jwks_cache_is_not_used_when_refresh_fails() -> None:
    responses = iter(
        [
            httpx.Response(200, json={"keys": [JWK_ONE]}),
            httpx.Response(503),
        ]
    )
    now = [0.0]

    def handler(_request: httpx.Request) -> httpx.Response:
        return next(responses)

    config = _config(jwks_cache_seconds=10)
    verifier = OidcJwtVerifier(
        config,
        CachingJwksProvider(
            config,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            monotonic=lambda: now[0],
        ),
    )
    verifier.verify(_token())
    now[0] = 11.0

    with pytest.raises(AuthenticationFailed):
        verifier.verify(_token())


def test_id_token_uses_audience_validation_when_explicitly_configured() -> None:
    claims = _claims(token_use="id", aud=CLIENT_ID)
    claims.pop("client_id")
    verifier = OidcJwtVerifier(
        _config(token_use="id"), StaticKeys({"key-one": KEY_ONE.public_key()})
    )
    assert verifier.verify(_token(claims=claims)).subject == "provider-subject"
