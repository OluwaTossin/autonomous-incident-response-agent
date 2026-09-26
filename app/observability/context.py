"""Validated correlation and protected log context."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator
from uuid import UUID, uuid4

_context: ContextVar[dict[str, str]] = ContextVar("aira_observability_context", default={})

LOG_IDENTIFIER_FIELDS = frozenset(
    {
        "correlation_id",
        "request_id",
        "organization_id",
        "workspace_id",
        "actor_id",
        "incident_id",
        "triage_run_id",
        "job_id",
        "dispatch_id",
        "integration_id",
        "execution_intent_id",
        "eventbridge_event_id",
    }
)


def valid_correlation_id(value: str | None) -> str | None:
    if value is None or len(value) > 64:
        return None
    try:
        parsed = UUID(value.strip())
    except (AttributeError, ValueError):
        return None
    return str(parsed) if parsed.int else None


def correlation_id(value: str | None = None) -> str:
    return valid_correlation_id(value) or str(uuid4())


def current_log_context() -> dict[str, str]:
    return dict(_context.get())


@contextmanager
def log_context(**fields: object) -> Iterator[dict[str, str]]:
    safe = {
        name: str(value)
        for name, value in fields.items()
        if name in LOG_IDENTIFIER_FIELDS and value is not None
    }
    merged = {**_context.get(), **safe}
    token = _context.set(merged)
    try:
        yield merged
    finally:
        _context.reset(token)
