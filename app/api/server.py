"""Run the API with uvicorn (`uv run serve-api`)."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("API_HOST", "127.0.0.1")
    port = int(os.environ.get("API_PORT", "8000"))
    uvicorn.run("app.api.main:app", host=host, port=port)
