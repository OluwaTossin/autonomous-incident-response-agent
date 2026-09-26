# AIRA Hosted Terraform

This is the Version 3 shared-SaaS AWS composition. The sibling `../envs/` and
`../modules/` trees remain the Version 2 deployment and are not dependencies of this
stack.

## Layout

- `modules/platform`: private networking, HTTPS edge, ECS, RDS, queues, object storage,
  Cognito, EventBridge, KMS, IAM, health checks, basic alarms, and autoscaling.
- `envs/dev`: one NAT gateway, smaller tasks, single-AZ RDS, 14-day logs, optional
  interface endpoints disabled.
- `envs/prod`: one NAT gateway per AZ, Multi-AZ RDS, two-task API/web baselines,
  interface endpoints, deletion protection, and 90-day logs.
- `customer-eventbridge`: customer-account module instantiated once per supported alarm
  region. It uses IAM/EventBridge trust and no customer access keys.

Environment roots require immutable image digests, an existing Route 53 zone, and explicit
account/domain values. Terraform creates secret containers but never secret versions;
operators populate those out of band before running migrations or services.

## Safe Validation

```bash
terraform fmt -check -recursive infra/terraform/hosted
terraform -chdir=infra/terraform/hosted/envs/dev init -backend=false
terraform -chdir=infra/terraform/hosted/envs/dev validate
terraform -chdir=infra/terraform/hosted/envs/prod init -backend=false
terraform -chdir=infra/terraform/hosted/envs/prod validate
```

Plans intentionally require the configured remote backend and an authenticated,
read-capable planning role. `terraform init -backend=false` supports validation but not a
plan for roots declaring the S3 backend; V3.22 did not bypass that control with a temporary
local state. Use placeholder/non-secret variables only for reviewed planning.

No Terraform apply was performed in V3.22.
