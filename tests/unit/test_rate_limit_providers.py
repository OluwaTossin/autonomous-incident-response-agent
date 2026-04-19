"""Rate-limit strings follow settings after ``reset_settings()`` (V2.9)."""

from __future__ import annotations

import pytest

from app.api.security import (
    admin_read_rate_limit_provider,
    admin_reindex_rate_limit_provider,
    admin_upload_rate_limit_provider,
    ingest_rate_limit_provider,
    triage_rate_limit_provider,
)
from app.config import get_settings, reset_settings


def test_triage_limit_provider_reflects_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_RATE_LIMIT_DISABLED", "0")
    monkeypatch.setenv("API_RATE_LIMIT_TRIAGE", "3/minute")
    reset_settings()
    try:
        assert get_settings().api_rate_limit_disabled is False
        assert triage_rate_limit_provider() == "3/minute"
    finally:
        reset_settings()


def test_admin_reindex_limit_provider_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_RATE_LIMIT_DISABLED", "0")
    monkeypatch.delenv("API_RATE_LIMIT_ADMIN_REINDEX", raising=False)
    reset_settings()
    try:
        assert admin_reindex_rate_limit_provider() == "2/minute"
    finally:
        reset_settings()


def test_when_disabled_providers_return_high_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_RATE_LIMIT_DISABLED", "1")
    reset_settings()
    try:
        assert triage_rate_limit_provider() == "100000/minute"
        assert ingest_rate_limit_provider() == "100000/minute"
        assert admin_read_rate_limit_provider() == "100000/minute"
        assert admin_upload_rate_limit_provider() == "100000/minute"
    finally:
        reset_settings()
