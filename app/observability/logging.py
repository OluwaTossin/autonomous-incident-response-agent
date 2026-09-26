"""JSON logging and centralized secret redaction for hosted runtimes."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

from app.observability.context import current_log_context

_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "password",
        "secret",
        "api_key",
        "access_token",
        "refresh_token",
        "session_token",
        "private_key",
        "database_url",
        "presigned_url",
    }
)
_BEARER = re.compile(r"(?i)\bbearer\s+\S+")
_URL_PASSWORD = re.compile(r"(?P<prefix>[a-z][a-z0-9+.-]*://[^:/\s]+:)[^@\s]+@", re.I)
_AWS_ACCESS_KEY = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.S,
)
_SENSITIVE_KEY = re.compile(
    r"(?:^|_)(?:authorization|cookie|password|passwd|secret|api_key|access_token|refresh_token|session_token|private_key|database_url|presigned_url)(?:_|$)",
    re.I,
)
_SENSITIVE_HEADER = re.compile(r"(?i)\b(authorization|cookie|set-cookie):\s*\S+")
_PRESIGNED_URL = re.compile(r"https?://\S+[?&]X-Amz-(?:Signature|Credential)=\S+", re.I)
_STANDARD_RECORD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__)


def redact(value: Any, *, key: str | None = None) -> Any:
    normalized_key = key.casefold().replace("-", "_") if key else ""
    if key and (
        normalized_key in {item.replace("-", "_") for item in _SENSITIVE_KEYS}
        or _SENSITIVE_KEY.search(normalized_key)
    ):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(name): redact(item, key=str(name)) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if not isinstance(value, str):
        return value
    redacted = _BEARER.sub("Bearer [REDACTED]", value)
    redacted = _URL_PASSWORD.sub(r"\g<prefix>[REDACTED]@", redacted)
    redacted = _AWS_ACCESS_KEY.sub("[REDACTED_AWS_ACCESS_KEY]", redacted)
    redacted = _SENSITIVE_HEADER.sub(r"\1: [REDACTED]", redacted)
    redacted = _PRESIGNED_URL.sub("[REDACTED_PRESIGNED_URL]", redacted)
    return _PRIVATE_KEY.sub("[REDACTED_PRIVATE_KEY]", redacted)


class JsonLogFormatter(logging.Formatter):
    def __init__(self, *, service: str, environment: str, build_sha: str) -> None:
        super().__init__()
        self._base = {
            "service": service,
            "environment": environment,
            "build_sha": build_sha,
        }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname.lower(),
            **self._base,
            **current_log_context(),
            "event": getattr(record, "event", record.name),
            "message": record.getMessage(),
        }
        for name, value in record.__dict__.items():
            if name not in _STANDARD_RECORD_FIELDS and name not in payload:
                payload[name] = value
        if record.exc_info:
            payload["error_category"] = getattr(
                record, "error_category", "internal"
            )
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(redact(payload), separators=(",", ":"), default=str)


def configure_json_logging(*, service: str, environment: str, build_sha: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonLogFormatter(
            service=service,
            environment=environment,
            build_sha=build_sha,
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    message: str,
    **fields: object,
) -> None:
    exc_info = bool(fields.pop("exc_info", False))
    logger.log(
        level,
        message,
        extra={"event": event, **redact(fields)},
        exc_info=exc_info,
    )
