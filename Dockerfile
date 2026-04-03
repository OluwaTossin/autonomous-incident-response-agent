# Phase 9 — API + optional Gradio (/ui). Build index on host, mount `.rag_index` read-only.
FROM python:3.12-slim-bookworm

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock README.md ./
COPY app ./app
COPY examples ./examples

RUN uv sync --frozen --no-dev --extra ui

ENV PATH="/app/.venv/bin:$PATH" \
    API_HOST=0.0.0.0 \
    API_PORT=8000 \
    ENABLE_GRADIO_UI=1

EXPOSE 8000

# Explicit probe (ECS/Fargate + ALB-style expectations; matches compose healthcheck).
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD curl --fail --silent --show-error --max-time 4 http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
