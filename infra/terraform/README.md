# Terraform — AWS (Phase 10)

Modular layout under [`modules/`](modules/) and **environment roots** [`envs/dev`](envs/dev/) and [`envs/prod`](envs/prod/).

| Module | Role |
|--------|------|
| `vpc` | VPC, public subnets (2 AZs), IGW, routes (Fargate tasks use **public IP**; no NAT in this lean cut) |
| `security_groups` | ALB ingress (80/443); ECS tasks only from ALB on API port |
| `ecr` | API image repository + lifecycle |
| `alb` | Internet ALB, target group (`ip`), health check `GET /health` |
| `ecs_fargate_api` | ECS cluster, Fargate service, task + execution IAM, CloudWatch logs, optional SSM for `OPENAI_API_KEY` |
| `monitoring` | Placeholder for Phase 12 (dashboards / alarms) |

## Credentials

Terraform and the AWS provider **do not read** repo-root `.env`. Either:

- `export AWS_REGION=… AWS_ACCESS_KEY_ID=… AWS_SECRET_ACCESS_KEY=…` (or use `AWS_PROFILE`), or  
- `aws configure`, then ensure `AWS_REGION` is set for the provider default.

Same variables are documented in [`.env.example`](../../.env.example) for convenience; load them into your shell before `terraform` commands.

## Dev (first apply)

```bash
cd infra/terraform/envs/dev
cp terraform.tfvars.example terraform.tfvars   # edit: aws_region, optional SSM name
terraform init
terraform plan
terraform apply
```

**SSM (recommended):** create a **SecureString** parameter (name must match `openai_api_key_ssm_parameter`, e.g. `/aira/dev/openai_api_key`). The task definition injects `OPENAI_API_KEY` from that ARN.

**ECR:** after apply, build and push an image tagged `latest` to the printed repository URL, then:

```bash
aws ecs update-service --cluster <cluster> --service <service> --force-new-deployment --region <region>
```

**RAG index:** the local stack bind-mounts `.rag_index/`. Fargate has **no** that mount unless you add EFS, bake the index into the image, or download at startup (Phase 11). Until then, tasks may be unhealthy or triage may degrade without an index.

**Bootstrap without a runnable image:** set `api_desired_count = 0` in `terraform.tfvars` so apply succeeds; scale up after push.

## Prod

Same flow from [`envs/prod`](envs/prod/) with stricter defaults (`alb_enable_deletion_protection`, higher `api_desired_count`, longer log retention). Tighten `alb_ingress_cidr_ipv4` when you front the ALB with CloudFront or a known egress range.

## Validate (no AWS apply)

From repo root:

```bash
cd infra/terraform/envs/dev && terraform init -backend=false && terraform validate
cd ../prod && terraform init -backend=false && terraform validate
```

Run the second line from `infra/terraform/envs` so `../prod` resolves to `envs/prod`.

## Remote state (optional)

Uncomment and fill the `backend "s3"` blocks in each env’s `providers.tf`, then `terraform init -migrate-state`.
