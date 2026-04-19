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

## Admin upload limits

- Max body size per file: **`ADMIN_UPLOAD_MAX_BYTES`** (default 5 MiB).
- Allowed extensions: `.md`, `.markdown`, `.txt`, `.log`, `.yaml`, `.yml`.
- Files are written only under **`workspaces/<WORKSPACE_ID>/data/{runbooks,incidents,logs,knowledge_base}/`** with a sanitized filename (no `..`, no path separators).

## Rate limits

Slowapi applies **`API_RATE_LIMIT_ADMIN_READ`**, **`API_RATE_LIMIT_ADMIN_UPLOAD`**, **`API_RATE_LIMIT_ADMIN_REINDEX`** when rate limiting is enabled (see `.env.example`). Disable all rate limits for tests with **`API_RATE_LIMIT_DISABLED=1`**.

## Threat model (honest limits)

- A compromised **operator machine** or leaked **admin** header can mutate corpus and trigger reindex.
- This product does **not** provide multi-tenant isolation or enterprise RBAC; treat the API as trusted-network or proxy-protected.
