variable "aws_region" {
  type        = string
  default     = "eu-west-1"
  description = "Region for the state bucket and lock table (must match env stacks using this backend)"
}

variable "state_bucket_name" {
  type        = string
  default     = ""
  description = "Globally unique S3 bucket name. Leave empty to use aira-tf-state-<account_id>."
}

variable "lock_table_name" {
  type        = string
  default     = "aira-terraform-locks"
  description = "DynamoDB table for S3 state locking (name unique per account+region)"
}
