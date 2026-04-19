"""Run the API with uvicorn (`uv run serve-api`)."""

from __future__ import annotations

import uvicorn


def main() -> None:
    from app.config import get_settings

    s = get_settings()
    host = s.api_host.strip() or "127.0.0.1"
    port = int(s.api_port)
    uvicorn.run("app.api.main:app", host=host, port=port)
