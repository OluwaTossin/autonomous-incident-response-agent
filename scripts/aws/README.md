# AWS helper scripts (Phase 11)

| Script | Purpose |
|--------|---------|
| [`push_api_to_ecr.sh`](push_api_to_ecr.sh) | Build, push immutable tag + **`:latest`**, **`terraform apply`** so ECS pins **digest** of **`:latest`** |

Full checklist: [`docs/deploy/aws-ecs.md`](../../docs/deploy/aws-ecs.md).
