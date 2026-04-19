# Phase 9 — API + optional Gradio (/ui). Phase 11 — stub `.rag_index` in-image; ECS overlays real index via `docker/bake_index_context/` (see push_api_to_ecr.sh).
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
COPY sample_data ./sample_data

RUN uv sync --frozen --no-dev --extra ui

# Default image index: CI and fresh `docker compose build` have no host `.rag_index/` (gitignored).
# ECS/ECR: `scripts/aws/push_api_to_ecr.sh` copies a host-built index into `docker/bake_index_context/`
# before `docker build`, which replaces this stub when `index.faiss` is present there.
COPY scripts/ci/stub_rag_index.py ./scripts/ci/stub_rag_index.py
RUN uv run python scripts/ci/stub_rag_index.py
COPY docker/bake_index_context/ /tmp/rag_bake/
RUN if [ -f /tmp/rag_bake/index.faiss ]; then rm -rf .rag_index && cp -a /tmp/rag_bake/. .rag_index/; fi \
    && rm -rf /tmp/rag_bake

# Non-root API process (V2.9). Bind-mounted `./workspaces` on the host should be writable by UID 1000
# on Linux (or override with `user:` in Compose / task definition to match your volume owner).
RUN groupadd --system --gid 1000 aira \
    && useradd --system --uid 1000 --gid aira --create-home --home-dir /app --shell /usr/sbin/nologin aira \
    && chown -R aira:aira /app
USER aira

ENV PATH="/app/.venv/bin:$PATH" \
    API_HOST=0.0.0.0 \
    API_PORT=8000 \
    ENABLE_GRADIO_UI=1 \
    RAG_INDEX_DIR=/app/.rag_index

EXPOSE 8000

# Explicit probe (ECS/Fargate + ALB-style expectations; matches compose healthcheck).
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD curl --fail --silent --show-error --max-time 4 http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
