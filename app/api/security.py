"""Optional shared API key and rate-limit key helper (browser + scripted clients)."""

from __future__ import annotations

import os

from fastapi import HTTPException, Request

API_KEY_HEADER = "x-api-key"


def api_key_configured() -> bool:
    return bool(os.environ.get("API_KEY", "").strip())


def _header_value(request: Request, name: str) -> str | None:
    v = request.headers.get(name)
    if v is not None and v != "":
        return v
    return None


def client_api_key(request: Request) -> str | None:
    """Value from ``x-api-key`` / ``X-Api-Key`` if present."""
    return _header_value(request, API_KEY_HEADER) or _header_value(request, "X-Api-Key")


def require_api_key_if_configured(request: Request) -> None:
    """When ``API_KEY`` is set in the environment, require a matching ``x-api-key`` header."""
    if not api_key_configured():
        return
    expected = os.environ["API_KEY"].strip()
    if client_api_key(request) != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def rate_limit_disabled() -> bool:
    return os.environ.get("API_RATE_LIMIT_DISABLED", "").lower() in ("1", "true", "yes")


def triage_rate_limit_string() -> str:
    if rate_limit_disabled():
        return "100000/minute"
    s = os.environ.get("API_RATE_LIMIT_TRIAGE", "").strip()
    return s if s else "10/minute"


def ingest_rate_limit_string() -> str:
    if rate_limit_disabled():
        return "100000/minute"
    s = os.environ.get("API_RATE_LIMIT_INGEST", "").strip()
    return s if s else "30/minute"
