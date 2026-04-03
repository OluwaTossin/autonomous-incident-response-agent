# Bootstrap — remote Terraform state (S3 + DynamoDB)

Creates **one S3 bucket** (versioned, encrypted, private) and **one DynamoDB table** for state locking. Intended to run **once per AWS account** (per region if you isolate by region).

**This stack uses local state** (not the bucket it creates). Do not add `backend.hcl` here — put **`backend.hcl` in `../envs/dev/` or `../envs/prod/`** (next to that env’s `providers.tf`) before `terraform init -backend-config=backend.hcl`.

## Prerequisites

- AWS credentials with permission to create S3 buckets and DynamoDB tables in **`eu-west-1`** (or your chosen `aws_region`).

## Apply

```bash
cd infra/terraform/bootstrap
terraform init
terraform apply
```

Note the outputs **`state_bucket`**, **`lock_table`**, **`aws_region`**, and the **`backend_hcl_snippet_*`** blocks.

## State object names (dev vs prod)

Both **`envs/dev`** and **`envs/prod`** use the **same bucket** and **DynamoDB lock table**; they are isolated by **different S3 keys**:

| Environment | S3 key (object path in the bucket) |
|-------------|-------------------------------------|
| Development | `aira/terraform/state/development.tfstate` |
| Production  | `aira/terraform/state/production.tfstate` |

Prod therefore has its **own** remote state file; it is not overwritten by dev.

### Renaming an existing dev state object (optional)

If you already stored state at the legacy key `aira/dev/terraform.tfstate`, move it before changing `key` in `backend.hcl`:

```bash
BUCKET="aira-tf-state-YOUR_ACCOUNT_ID"
REGION="eu-west-1"
aws s3api head-object --bucket "$BUCKET" --key aira/dev/terraform.tfstate --region "$REGION"
aws s3 mv "s3://${BUCKET}/aira/dev/terraform.tfstate" "s3://${BUCKET}/aira/terraform/state/development.tfstate" --region "$REGION"
```

Then set `key` in **`envs/dev/backend.hcl`** to `aira/terraform/state/development.tfstate` and run **`terraform init -reconfigure`**.

## Destroy

Removing the bucket risks **losing all infrastructure state**. The S3 bucket has **`prevent_destroy`**; remove that lifecycle block only if you intentionally tear down remote state (after migrating elsewhere).

To delete the DynamoDB lock table and bucket after emptying versions/objects, use the AWS console or CLI per your retention policy.
