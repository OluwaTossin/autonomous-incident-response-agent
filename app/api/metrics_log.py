"""Single-line JSON metrics for CloudWatch Logs metric filters (Phase 13).

Emit one JSON object per line to stdout so ``{ $.event = \"triage_metrics\" }`` filters match.
Disable with ``TRIAGE_METRICS_LOG_DISABLE=1`` (e.g. noisy local dev).
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any


def triage_metrics_log_disabled() -> bool:
    return os.environ.get("TRIAGE_METRICS_LOG_DISABLE", "").lower() in ("1", "true", "yes")


def write_triage_metrics_line(payload: dict[str, Any]) -> None:
    if triage_metrics_log_disabled():
        return
    line = json.dumps(payload, separators=(",", ":"), default=str, ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()
