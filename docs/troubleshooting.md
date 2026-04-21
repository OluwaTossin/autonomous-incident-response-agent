# Troubleshooting

Symptoms-first hints for **local** and **Docker Compose** setups. For AWS/ECS, start with [`deploy/aws-ecs.md`](deploy/aws-ecs.md) and CloudWatch logs.

### AWS / Terraform (quick pointers)

- **“Failed to read file … `backend.hcl`”** — Create **`infra/terraform/envs/<env>/backend.hcl`** from **`backend.hcl.example`** and bootstrap outputs; it is **not** in Git. See [`infra/terraform/README.md`](../../infra/terraform/README.md).
- **CloudFront `AccessDenied` / account must be verified** — Set **`enable_triage_ui_cloudfront = false`** and use the S3 website UI until AWS Support enables CloudFront on the account — table row in [`deploy/aws-ecs.md`](deploy/aws-ecs.md) §7.
- **Bootstrap `BucketAlreadyOwnedByYou` / DynamoDB already exists** — Import existing resources into bootstrap state or skip re-bootstrap and only create **`backend.hcl`** from known bucket names — [`infra/terraform/bootstrap/README.md`](../../infra/terraform/bootstrap/README.md).

## API / browser

### CORS errors from the Next.js UI

The API allows origins from **`CORS_ORIGINS`** (default includes `http://localhost:3000` and `http://127.0.0.1:3000`). If you use another origin or port, add it to **`CORS_ORIGINS`** in `.env` (comma-separated) and restart the API.

Ensure **`NEXT_PUBLIC_API_BASE_URL`** (or legacy **`NEXT_PUBLIC_TRIAGE_API_BASE`**) in the **frontend** build points at the URL the **browser** uses to reach the API (not an internal Docker hostname like `http://api:8000`).

### `401 Unauthorized` on `/triage` or `/ingest-incident`

When **`API_KEY`** is set, clients must send **`x-api-key`** with the same value. The Next.js app can use **`NEXT_PUBLIC_TRIAGE_API_KEY`** at build time (demo only) or you inject the header at a reverse proxy — see [`security.md`](security.md).

### `401` on `GET /operator-config`

Same **`x-api-key`** requirement when **`API_KEY`** is configured.

### `503` on `/admin/*` with `admin_disabled`

**`ADMIN_API_KEY`** is unset. Set it in `.env` and restart the API, or use only filesystem/CLI ingestion without admin HTTP routes.

### `403` when calling admin routes

You sent the **triage** key in **`x-admin-api-key`**. Use **`ADMIN_API_KEY`** (must differ from **`API_KEY`**).

### `413` / `415` on `POST /admin/upload`

Body over **`ADMIN_UPLOAD_MAX_BYTES`** or extension not in the allowlist (`.md`, `.markdown`, `.txt`, `.log`, `.yaml`, `.yml`). See [`security.md`](security.md).

### `429 Rate limit exceeded`

Slowapi limits apply when **`API_RATE_LIMIT_DISABLED`** is not set to `1`. Raise **`API_RATE_LIMIT_TRIAGE`** (or the relevant **`API_RATE_LIMIT_*`**) or disable limits only in trusted dev — see [`configuration.md`](configuration.md).

## Index / RAG

### Triage returns empty or generic evidence

- Confirm an index exists under **`workspaces/<WORKSPACE_ID>/index/`** (or **`RAG_INDEX_DIR`**).  
- Rebuild: [`reindexing.md`](reindexing.md).  
- Check **`AIRA_DATA_MODE`**: in **`user`** mode an empty workspace `data/` has no demo fallback — see [`bring-your-own-data.md`](bring-your-own-data.md).

### `product-build-index` warnings about missing subdirs

Optional folders (`runbooks/`, etc.) can be empty; add files as needed. Warnings about unsupported extensions (e.g. `.pdf`) mean those files are skipped until converted or moved.

## Docker Compose

### Permission denied writing under `./workspaces`

The API container runs as **UID 1000** (`aira`). On Linux, **`chown -R 1000:1000 workspaces`** (or your chosen UID) on the host, or set the Compose **`user:`** field to match the owner of the bind-mounted directory. See [`security.md`](security.md).

### Frontend shows wrong API or cannot connect

Rebuild the **frontend** image after changing **`NEXT_PUBLIC_API_BASE_URL`** — it is baked in at build time (`docker compose build frontend` or full stack rebuild).

### Health check failing

Ensure **`OPENAI_API_KEY`** (or provider key) is available inside the container via **`.env`** / Compose **`env_file`**, and that the index path is readable. Check **`docker compose logs api`**.

## Still stuck

- OpenAPI: **`/docs`** on the running API  
- Product doc index: [`README.md`](README.md) in this folder  
- Contributing / CI: [`contributing.md`](contributing.md)  
