# Next.js operator console (Phase 12 + V2.8) — shipped

Operational **AIRA** UI: **Triage**, **Setup** (corpus upload + reindex), and **Configuration** (read-only effective config + safe overrides via API). Separate from Phase 7 Gradio (validation / debug). For **demos**, **portfolio**, and internal SRE workflows.

## Troubleshooting

**`Cannot find module './NNN.js'` (webpack / `.next`):** stop `npm run dev`, delete the cache, restart:

```bash
rm -rf .next && npm run dev
# or: npm run dev:clean
```

## Run locally

1. **API** (from repo root): `uv sync --extra dev`, `uv run rag-build`, `uv run serve-api` → API on **http://127.0.0.1:8000**  
   FastAPI enables **CORS** for `http://localhost:3000` and `http://127.0.0.1:3000` by default (`CORS_ORIGINS` in repo-root `.env` — see [`.env.example`](../.env.example)).  
   If **`API_KEY`** is set on the API, add **`NEXT_PUBLIC_TRIAGE_API_KEY`** with the same value in **`.env.local`** (see [`.env.example`](.env.example)) so the UI sends **`x-api-key`**.

2. **Frontend** (this directory):
   ```bash
   npm install
   npm run dev
   ```
   Open **http://localhost:3000**.  
   **`npm run dev`** loads **[`.env.development`](.env.development)** (defaults to local API; set **`NEXT_PUBLIC_API_BASE_URL`** to the dev **`alb_url`** from Terraform or use **`.env.local`**).  
   **`next build && next start`** uses **[`.env.production`](.env.production)** unless **`deploy_frontend_cdn.sh`** exports **`NEXT_PUBLIC_API_BASE_URL`** from Terraform.

3. **Docker Compose API** on **:18080**: in `.env.local` set `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:18080` (or legacy `NEXT_PUBLIC_TRIAGE_API_BASE`). The product Compose file also builds a **static UI image** (`frontend/Dockerfile`) with that URL baked in for the same host port defaults.

### Docker image (static UI)

From the **repository root** (build arg must be a URL your **browser** can reach):

```bash
docker build -f frontend/Dockerfile --build-arg NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:18080 -t aira-ui:local ./frontend
```

### Deploy UI to S3 + CloudFront (static export)

The app uses Next **`output: 'export'`** ([`next.config.ts`](next.config.ts)) — no Node server; files go to **S3**. Terraform defaults to **CloudFront** (private bucket + **OAC**, HTTPS). Set **`enable_triage_ui_cloudfront = false`** in `terraform.tfvars` only if your account cannot create distributions (falls back to public S3 website / HTTP).

1. **Terraform (dev)** — creates bucket + distribution:

   ```bash
   cd infra/terraform/envs/dev
   terraform init -backend-config=backend.hcl   # if not already
   terraform apply
   ```

2. **Build & upload** (from repo root; bakes **`NEXT_PUBLIC_API_BASE_URL`** from Terraform **`alb_url`** — e.g. dev ALB):

   ```bash
   ./scripts/aws/deploy_frontend_cdn.sh dev   # or: prod
   ```

3. **CORS** — use the printed **`triage_ui_url`** (HTTPS CloudFront by default) and append it to **`cors_origins`** in **`terraform.tfvars`**, then **`terraform apply`** again so the **ECS** API allows that origin. You can keep **`http://localhost:3000`** entries for local browser → cloud API experiments; that does not change **`docker compose`** on your machine.

4. **Local preview of the static `out/` folder** (after `npm run build`):

   ```bash
   npm start
   ```

### Point the UI at a deployed ALB (dev / prod)

1. From Terraform: `terraform -chdir=infra/terraform/envs/dev output -raw alb_url` (or `prod`).
2. **`frontend/.env.local`** (no trailing slash on the URL):

   ```bash
   NEXT_PUBLIC_API_BASE_URL=http://aira-dev-alb-xxxx.region.elb.amazonaws.com
   ```

3. **Repo-root `.env`** (API server): extend **`CORS_ORIGINS`** so it includes wherever the Next app is served from, e.g. `http://localhost:3000` for local dev hitting the cloud API, or a Vercel origin for a hosted UI:

   ```bash
   CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,https://example-app.vercel.app
   ```

4. Restart **`uv run serve-api`** (or redeploy ECS) so CORS picks up the change, then **`npm run dev`** so Next embeds the new `NEXT_PUBLIC_*` value.

Optional: **`NEXT_PUBLIC_RUNBOOK_DOCS_BASE`** — base URL for `RB-*` links in recommended actions (see `.env.example`).

## Backend contracts

| Action | Endpoint |
|--------|----------|
| Run triage | `POST /triage` |
| Feedback | `POST /n8n/triage-feedback` (`triage_id`, `diagnosis_correct`, `actions_useful`, `notes`) |

**Retrieval similarity scores** are not on `/triage` yet; the **Evidence** panel uses `evidence[]` (`type`, `source`, `reason`).

## Stack

Next.js 15 (App Router), TypeScript, Tailwind v4, **Monaco** (`@monaco-editor/react`), **Sonner** toasts.

## Implementation status

- [x] App shell, incident JSON editor, sample dropdown, Run triage
- [x] Triage output (severity colors, summary, root cause, actions, `triage_id`)
- [x] Evidence table, timeline, feedback (yes/no + notes)
- [x] **`NEXT_PUBLIC_API_BASE_URL`** (ALB-ready) + legacy `NEXT_PUBLIC_TRIAGE_API_BASE`, timeouts, FastAPI CORS
- [x] Evidence drill-down (snippet expand + full-context modal), operational actions (commands / URLs / RB-* links)
- [x] Loading overlay, disabled controls, triage error banner + retry, feedback error + retry
- [ ] Optional: Recharts, `/triage` debug payload for retrieval scores

Spec: root [`README.md`](../README.md) Phase 12 · [`execution-v1.md`](../docs/build-journey/execution-v1.md).
