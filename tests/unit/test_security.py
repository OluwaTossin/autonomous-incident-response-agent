"""Unit tests for optional API key gate (no FastAPI app import required)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api.security import (
    api_key_configured,
    client_api_key,
    require_api_key_if_configured,
)


def test_api_key_not_configured_allows_empty_header() -> None:
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("API_KEY", raising=False)
        req = MagicMock()
        req.headers = {}
        require_api_key_if_configured(req)  # no-op


def test_api_key_configured_rejects_missing_header() -> None:
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("API_KEY", "secret")
        req = MagicMock()
        req.headers = {}
        with pytest.raises(HTTPException) as ei:
            require_api_key_if_configured(req)
        assert ei.value.status_code == 401
        assert ei.value.detail == "Unauthorized"


def test_api_key_configured_rejects_wrong_header() -> None:
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("API_KEY", "secret")
        req = MagicMock()
        req.headers = {"x-api-key": "wrong"}
        with pytest.raises(HTTPException) as ei:
            require_api_key_if_configured(req)
        assert ei.value.status_code == 401


def test_api_key_configured_accepts_match() -> None:
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("API_KEY", "secret")
        req = MagicMock()
        req.headers = {"x-api-key": "secret"}
        require_api_key_if_configured(req)


def test_client_api_key_reads_x_api_key() -> None:
    req = MagicMock()
    req.headers = {"x-api-key": "k"}
    assert client_api_key(req) == "k"


def test_api_key_configured_false_when_empty() -> None:
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("API_KEY", "   ")
        assert api_key_configured() is False
