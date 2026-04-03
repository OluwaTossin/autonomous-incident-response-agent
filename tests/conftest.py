"""Global test defaults (before ``app.api.main`` is imported)."""

from __future__ import annotations

import os

os.environ["ENABLE_GRADIO_UI"] = "0"
# Before any test module imports ``app.api.main``, disable slowapi enforcement (deterministic CI).
os.environ.setdefault("API_RATE_LIMIT_DISABLED", "1")
