"""Optional shared API key and rate-limit key helper (browser + scripted clients)."""

from __future__ import annotations

from fastapi import HTTPException, Request

from app.config import get_settings

API_KEY_HEADER = "x-api-key"
ADMIN_API_KEY_HEADER = "x-admin-api-key"


def api_key_configured() -> bool:
    return bool(get_settings().api_key.strip())


def _header_value(request: Request, name: str) -> str | None:
    v = request.headers.get(name)
    if v is not None and v != "":
        return v
    return None


def client_api_key(request: Request) -> str | None:
    """Value from ``x-api-key`` / ``X-Api-Key`` if present."""
    return _header_value(request, API_KEY_HEADER) or _header_value(request, "X-Api-Key")


def admin_api_key_configured() -> bool:
    return bool(get_settings().admin_api_key.strip())


def client_admin_api_key(request: Request) -> str | None:
    return _header_value(request, ADMIN_API_KEY_HEADER) or _header_value(request, "X-Admin-Api-Key")


def require_admin_api_key(request: Request) -> None:
    """Require ``ADMIN_API_KEY`` via ``x-admin-api-key`` (mutating and listing admin routes)."""
    if not admin_api_key_configured():
        raise HTTPException(
            status_code=503,
            detail={"error": "admin_disabled", "message": "Set ADMIN_API_KEY to enable /admin routes."},
        )
    expected = get_settings().admin_api_key.strip()
    triage_key = get_settings().api_key.strip()
    got = client_admin_api_key(request)
    if got != expected:
        if triage_key and got == triage_key:
            raise HTTPException(
                status_code=403,
                detail={"error": "forbidden", "message": "Use x-admin-api-key with ADMIN_API_KEY, not the triage API_KEY."},
            )
        raise HTTPException(
            status_code=401,
            detail={"error": "unauthorized", "message": "Invalid or missing x-admin-api-key."},
        )


def require_api_key_if_configured(request: Request) -> None:
    """When ``API_KEY`` is set in the environment, require a matching ``x-api-key`` header."""
    if not api_key_configured():
        return
    expected = get_settings().api_key.strip()
    if client_api_key(request) != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def rate_limit_disabled() -> bool:
    return get_settings().api_rate_limit_disabled


def triage_rate_limit_string() -> str:
    if rate_limit_disabled():
        return "100000/minute"
    s = get_settings().api_rate_limit_triage.strip()
    return s if s else "10/minute"


def ingest_rate_limit_string() -> str:
    if rate_limit_disabled():
        return "100000/minute"
    s = get_settings().api_rate_limit_ingest.strip()
    return s if s else "30/minute"


def admin_read_rate_limit_string() -> str:
    if rate_limit_disabled():
        return "100000/minute"
    s = get_settings().api_rate_limit_admin_read.strip()
    return s if s else "120/minute"


def admin_upload_rate_limit_string() -> str:
    if rate_limit_disabled():
        return "100000/minute"
    s = get_settings().api_rate_limit_admin_upload.strip()
    return s if s else "20/minute"


def admin_reindex_rate_limit_string() -> str:
    if rate_limit_disabled():
        return "100000/minute"
    s = get_settings().api_rate_limit_admin_reindex.strip()
    return s if s else "2/minute"


# Zero-arg callables for slowapi (evaluated per request so ``reset_settings()`` picks up new env).
def triage_rate_limit_provider() -> str:
    return triage_rate_limit_string()


def ingest_rate_limit_provider() -> str:
    return ingest_rate_limit_string()


def admin_read_rate_limit_provider() -> str:
    return admin_read_rate_limit_string()


def admin_upload_rate_limit_provider() -> str:
    return admin_upload_rate_limit_string()


def admin_reindex_rate_limit_provider() -> str:
    return admin_reindex_rate_limit_string()
