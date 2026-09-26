"""Deterministic helpers used to document and test internal SLO math."""

from __future__ import annotations


def error_budget_seconds(target: float, window_seconds: int) -> float:
    if not 0 < target < 1 or window_seconds <= 0:
        raise ValueError("SLO target and window are invalid")
    return (1 - target) * window_seconds


def burn_rate(error_ratio: float, target: float) -> float:
    if not 0 <= error_ratio <= 1 or not 0 < target < 1:
        raise ValueError("Error ratio and SLO target are invalid")
    return error_ratio / (1 - target)


def api_request_is_eligible(operation: str, status_code: int) -> bool:
    if operation in {"healthz", "readyz"}:
        return False
    return not 400 <= status_code < 500
