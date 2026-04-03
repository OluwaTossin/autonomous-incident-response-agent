"""Triage observability: stdout JSON for CloudWatch metric filters + structured app logs.

One JSON object per line (``aira.triage`` logger + stdout) so Logs Insights can correlate by
``triage_id``, ``stack_environment``, ``outcome``, ``duration_ms``, ``severity`` / ``severity_metric``,
``escalate`` / ``escalate_str``, and token fields.

Disable with ``TRIAGE_METRICS_LOG_DISABLE=1`` (e.g. tests, noisy local dev).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

_triage_log = logging.getLogger("aira.triage")


def triage_metrics_log_disabled() -> bool:
    return os.environ.get("TRIAGE_METRICS_LOG_DISABLE", "").lower() in ("1", "true", "yes")


def write_triage_metrics_line(payload: dict[str, Any]) -> None:
    """Emit JSON to stdout and ``aira.triage`` (same line) for metric filters + traceability."""
    if triage_metrics_log_disabled():
        return
    line = json.dumps(payload, separators=(",", ":"), default=str, ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()
    _triage_log.info("%s", line)
