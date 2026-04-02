"""Global test defaults (before ``app.api.main`` is imported)."""

from __future__ import annotations

import os

os.environ["ENABLE_GRADIO_UI"] = "0"
