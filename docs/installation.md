# Installation (self-hosted)

This guide gets a **single-tenant** AIRA stack running: API + optional Gradio, workspace layout, and (recommended) the **Next.js** operator UI via Docker Compose.

## Prerequisites

- **Git**, **Docker** + **Docker Compose v2** (for the default product path)
- **[uv](https://docs.astral.sh/uv/)** (Python 3.12 toolchain and CLI entrypoints)
- An **OpenAI-compatible** API key for embeddings + chat (`OPENAI_API_KEY`, or `OPENROUTER_API_KEY` per [`.env.example`](../.env.example))

## 1. Clone and Python environment

```bash
git clone https://github.com/OluwaTossin/autonomous-incident-response-agent.git
cd autonomous-incident-response-agent
uv sync --extra dev          # add --extra ui if you want Gradio at /ui
```

## 2. Secrets and config

```bash
cp .env.example .env
```

Edit **`.env`** at the repo root (never commit it):

- Set **`OPENAI_API_KEY`** (required for triage and index builds).
- For production-style auth, set distinct **`API_KEY`** (triage / `x-api-key`) and **`ADMIN_API_KEY`** (admin routes / `x-admin-api-key`). See [`security.md`](security.md).

Optional non-secret tuning: copy [`config.example.yaml`](../config.example.yaml) to `config.yaml` and set `CONFIG_YAML=config.yaml`. See [`configuration.md`](configuration.md).

## 3. Workspace and first index

Default workspace id is **`default`** (`WORKSPACE_ID`).

```bash
uv run product-build-index --workspace default
```

Or: [`../scripts/product/rebuild-index.sh`](../scripts/product/rebuild-index.sh). Corpus sources depend on **`AIRA_DATA_MODE`** — see [`bring-your-own-data.md`](bring-your-own-data.md).

## 4. Run the API (host only)

```bash
uv run serve-api
```

- API: **`http://127.0.0.1:8000`** (or `API_HOST` / `API_PORT` from `.env`)
- OpenAPI: **`/docs`**, health: **`GET /health`**

## 5. Run the full product stack (Docker Compose)

From the repo root (after the index build above):

```bash
./scripts/product/start.sh
# or: docker compose up -d --build
```

Default URLs:

- API: **`http://127.0.0.1:18080`** (`COMPOSE_API_PORT` to change)
- Next.js (static): **`http://127.0.0.1:3000`**
- Optional **n8n**: `docker compose --profile automation up -d --build`

Compose bind-mounts **`./workspaces`** into the container. The API image runs as **UID 1000**; on Linux, ensure `./workspaces` is writable by that user or set Compose **`user:`** to match your host UID (see [`security.md`](security.md) and [`troubleshooting.md`](troubleshooting.md)).

## 6. Next steps

- **Configure** behaviour: [`configuration.md`](configuration.md)
- **Add your data** and reindex: [`bring-your-own-data.md`](bring-your-own-data.md), [`reindexing.md`](reindexing.md)
- **Problems**: [`troubleshooting.md`](troubleshooting.md)
- **AWS / ECS + hosted operator UI**: [`deploy/aws-ecs.md`](deploy/aws-ecs.md) — Terraform defaults to **S3 + CloudFront (HTTPS)** for the static Next.js UI; local Compose is unchanged.
