# AWS helper scripts (Phase 11–12)

| Script | Purpose |
|--------|---------|
| [`push_api_to_ecr.sh`](push_api_to_ecr.sh) | Build, push immutable tag + **`:latest`**, **`terraform apply`** so ECS pins **digest** of **`:latest`** |
| [`deploy_frontend_cdn.sh`](deploy_frontend_cdn.sh) | Phase 12 — `next build` (static export), **`aws s3 sync`**, optional CloudFront invalidation |
| [`verify_triage_cors_preflight.sh`](verify_triage_cors_preflight.sh) | Phase 12 — **`OPTIONS /triage`** with **`Origin: triage_ui_url`** (smoke CORS) |

Full checklist: [`docs/deploy/aws-ecs.md`](../../docs/deploy/aws-ecs.md).
