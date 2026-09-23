"""Opaque service-account credential issuance and verification."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass

from app.auth.errors import AuthenticationFailed

_CREDENTIAL_PATTERN = re.compile(
    r"^aira_sa_(?P<lookup>[A-Za-z0-9_-]{16})\.(?P<secret>[A-Za-z0-9_-]{43})$"
)
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_KEY_LENGTH = 32


@dataclass(frozen=True, slots=True, repr=False)
class IssuedServiceAccountSecret:
    lookup_id: str
    credential: str
    verifier: bytes
    salt: bytes
    algorithm: str = "scrypt-v1"

    def __repr__(self) -> str:
        return (
            "IssuedServiceAccountSecret(lookup_id="
            f"{self.lookup_id!r}, credential='<redacted>', verifier='<redacted>')"
        )


def issue_service_account_secret() -> IssuedServiceAccountSecret:
    lookup_id = secrets.token_urlsafe(12)
    secret = secrets.token_urlsafe(32)
    salt = secrets.token_bytes(16)
    return IssuedServiceAccountSecret(
        lookup_id=lookup_id,
        credential=f"aira_sa_{lookup_id}.{secret}",
        verifier=_derive_verifier(secret, salt),
        salt=salt,
    )


def parse_service_account_credential(credential: str) -> tuple[str, str]:
    match = _CREDENTIAL_PATTERN.fullmatch(credential)
    if match is None:
        raise AuthenticationFailed("Authentication failed")
    return match.group("lookup"), match.group("secret")


def verify_service_account_secret(secret: str, salt: bytes, expected: bytes) -> bool:
    calculated = _derive_verifier(secret, salt)
    return hmac.compare_digest(calculated, expected)


def _derive_verifier(secret: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        secret.encode("ascii"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_KEY_LENGTH,
    )
