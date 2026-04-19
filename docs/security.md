# Security (self-hosted)

This document is the **Version 2 security baseline** for operators and deployers. It complements the **V2.9** integration tests under `tests/integration/test_security_baseline_v29.py` and `tests/integration/test_admin_routes.py`.

## API keys

| Key | Header | Purpose |
|-----|--------|---------|
| **`API_KEY`** | `x-api-key` | `POST /triage`, `POST /ingest-incident`, and **`GET /operator-config`** when the key is configured. |
| **`ADMIN_API_KEY`** | `x-admin-api-key` | **`/admin/*`** upload, list files, reindex, index status, **`PATCH /admin/operator-settings`**. |

Use **different** values for `API_KEY` and `ADMIN_API_KEY` so a browser or integration that only triages cannot upload or reindex.

If **`ADMIN_API_KEY`** is unset, **`/admin/*`** returns **503** (admin disabled).

**Integration coverage:** missing or wrong admin header → **401**; sending the triage key in **`x-admin-api-key`** → **403**; triage routes return **401** when `API_KEY` is set but `x-api-key` is missing or wrong.

## TLS and reverse proxy

For anything beyond **one trusted operator on loopback**:

- Terminate **TLS** at a reverse proxy (Caddy, nginx, AWS ALB, etc.).
- Prefer **private networks** or firewall rules so the API is not world-reachable without authentication.
- Inject **`x-admin-api-key`** and **`x-api-key`** from **server-side** environment at the proxy when using the “no secrets in the browser” pattern (see below).

## Docker Compose vs ECS

| Concern | Compose (local product stack) | ECS / Fargate (typical) |
|----------|-------------------------------|-------------------------|
| **Secrets** | Repo-root `.env` (never commit); optional SSM-style injection via your shell/CI | Task definition secrets from **SSM** / **Secrets Manager**; IAM least-privilege |
| **Bind mounts** | `./workspaces`, `./data`, `./sample_data` mapped into the container; files on disk are owned by your **host UID** | Prefer **EFS** or bake read-only corpus; index path via `RAG_INDEX_DIR` / workspace layout |
| **API listen** | `API_HOST=0.0.0.0` **inside** the container is normal so **published ports** work; control exposure on the **host** firewall | Security groups on the service; ALB only where needed |
| **Process user** | The API **Dockerfile** runs **uvicorn as UID 1000** (`aira`). Ensure bind-mounted directories are writable by that UID on Linux, or set Compose **`user:`** to match the host directory owner | Set the task **`user`** to a non-root UID aligned with your image |

The API image listens on **`0.0.0.0:8000`** so port mapping works; that is **not** a substitute for network policy on untrusted networks.

## Next.js / static UI

Do **not** embed `ADMIN_API_KEY` or `API_KEY` in the static bundle. Prefer a **reverse proxy** (Caddy, nginx) on the same origin that injects `x-admin-api-key` and `x-api-key` from server-side environment for operator-only setups.

### Operator console (V2.8)

The **Next.js** app under `frontend/` ships as a **static export** (`npm run build` → `frontend/out`). It includes **Setup** (upload, file list, reindex), **Configuration** (read `GET /operator-config` with the triage key pattern; save via `PATCH /admin/operator-settings` with the admin key pattern), and **Triage**.

**Patterns:**

1. **Reverse proxy (recommended for shared host):** Terminate TLS at the edge, serve the static UI and proxy `/admin/*`, `/operator-config`, `/triage`, etc. to the API. Inject `x-admin-api-key` / `x-api-key` from container or host env. At **Next.js build time**, set `NEXT_PUBLIC_ADMIN_PROXY_INJECTS_HEADERS=1` so the browser omits `x-admin-api-key` (the proxy adds it). Optionally inject triage `x-api-key` the same way and omit `NEXT_PUBLIC_TRIAGE_API_KEY`.
2. **Split origin (default Compose):** API on one port, UI on another. The UI calls `NEXT_PUBLIC_API_BASE_URL`. Paste the **admin key once per tab** — it is stored in **`sessionStorage`** only (`Setup` / `Configuration`), not in the build. The triage key can use the same session pattern later; today the optional `NEXT_PUBLIC_TRIAGE_API_KEY` remains a **demo-only** escape hatch.
3. **Release check:** after `npm run build`, run `./scripts/product/verify-frontend-bundle.sh` to reject accidental `ADMIN_API_KEY` / `NEXT_PUBLIC_ADMIN_API_KEY` strings under `frontend/out`.

## Admin upload limits

- Max body size per file: **`ADMIN_UPLOAD_MAX_BYTES`** (default 5 MiB).
- Allowed extensions: `.md`, `.markdown`, `.txt`, `.log`, `.yaml`, `.yml`.
- Files are written only under **`workspaces/<WORKSPACE_ID>/data/{runbooks,incidents,logs,knowledge_base}/`** with a sanitized filename (no `..`, no path separators).

Unsupported extensions return **415**; oversize bodies return **413** (covered in integration tests).

## Reindex and flood protection

- **`POST /admin/reindex`** is **synchronous** and can run for a long time; only **one** reindex runs at a time per API worker. A second overlapping call receives **409** (`reindex_in_progress`) when the non-reentrant lock is held.
- **Rate limit:** **`API_RATE_LIMIT_ADMIN_REINDEX`** (default **`2/minute`** per SlowAPI key / IP) limits how often reindex can be started when rate limiting is enabled.

## Rate limits

Slowapi applies per-route limits using **zero-arg providers** so values refresh after config reloads:

- **`API_RATE_LIMIT_TRIAGE`**, **`API_RATE_LIMIT_INGEST`**
- **`API_RATE_LIMIT_ADMIN_READ`**, **`API_RATE_LIMIT_ADMIN_UPLOAD`**, **`API_RATE_LIMIT_ADMIN_REINDEX`**

When **`API_RATE_LIMIT_DISABLED=1`**, limits become a very high ceiling (tests and local debugging). With limits enabled, exceeding a route’s quota returns **429** (integration test covers triage burst).

Optional Slowapi env vars (`RATELIMIT_*`) from the upstream library are **not** required for this product; defaults come from **`app/config/settings.py`** and `.env.example`.

## Dependencies and supply chain

- Pin runtime dependencies in **`uv.lock`**; rebuild images after `uv lock` updates.
- Keep **`python-multipart`** (FastAPI form uploads) and other HTTP stack packages on supported versions via CI.
- **Container:** non-root user in the API **Dockerfile** (see above); avoid running `latest` tags for production without a digest pin in your own pipeline.

## Threat model (honest limits) — explicit non-goals

**What this product does not guarantee:**

- **No multi-tenant isolation:** one deployment assumes one operator team; it is not a SaaS control plane.
- **No enterprise RBAC:** only shared secrets (`API_KEY`, `ADMIN_API_KEY`); no per-user audit identities in the OSS core.
- **No protection against a compromised operator machine:** a stolen admin header or session can mutate corpus and trigger reindex.
- **No DLP or malware scanning** of uploaded text files beyond extension and size checks; do not ingest untrusted archives as “documents” without your own pipeline.
- **No guarantee under hostile internet exposure** of an admin-enabled API without TLS, proxy-injected headers, and network segmentation.
- **Rate limits are per process:** multiple replicas behind a load balancer each enforce their own counters; use edge rate limiting for global abuse protection.

**What sensible self-hosting still assumes:**

- You configure **distinct** triage and admin keys in production.
- You place the API on a **trusted network** or behind a **reverse proxy** with TLS and least-privilege env injection.
