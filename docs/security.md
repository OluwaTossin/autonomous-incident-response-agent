# Security (self-hosted)

## API keys

| Key | Header | Purpose |
|-----|--------|--------|
| **`API_KEY`** | `x-api-key` | `POST /triage`, `POST /ingest-incident` when the key is configured. |
| **`ADMIN_API_KEY`** | `x-admin-api-key` | **`/admin/*`** upload, list files, reindex, index status. |

Use **different** values for `API_KEY` and `ADMIN_API_KEY` so a browser or integration that only triages cannot upload or reindex.

If **`ADMIN_API_KEY`** is unset, **`/admin/*`** returns **503** (admin disabled).

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

## Rate limits

Slowapi applies **`API_RATE_LIMIT_ADMIN_READ`**, **`API_RATE_LIMIT_ADMIN_UPLOAD`**, **`API_RATE_LIMIT_ADMIN_REINDEX`** when rate limiting is enabled (see `.env.example`). Disable all rate limits for tests with **`API_RATE_LIMIT_DISABLED=1`**.

## Threat model (honest limits)

- A compromised **operator machine** or leaked **admin** header can mutate corpus and trigger reindex.
- This product does **not** provide multi-tenant isolation or enterprise RBAC; treat the API as trusted-network or proxy-protected.
