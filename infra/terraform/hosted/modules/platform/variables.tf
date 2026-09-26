variable "application" {
  type    = string
  default = "aira"
}
variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "environment must be dev or prod"
  }
}
variable "aws_region" { type = string }
variable "aws_account_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must contain 12 digits"
  }
}
variable "availability_zones" {
  type = list(string)
  validation {
    condition     = length(var.availability_zones) >= 2
    error_message = "At least two availability zones are required"
  }
}
variable "vpc_cidr" { type = string }
variable "route53_zone_id" { type = string }
variable "web_hostname" { type = string }
variable "api_hostname" { type = string }
variable "nat_gateway_mode" {
  type = string
  validation {
    condition     = contains(["single", "per_az"], var.nat_gateway_mode)
    error_message = "nat_gateway_mode must be single or per_az"
  }
}
variable "enable_interface_endpoints" { type = bool }
variable "enable_deletion_protection" { type = bool }
variable "log_retention_days" { type = number }
variable "force_destroy_nonproduction" { type = bool }
variable "enable_runtime_services" {
  description = "Start hosted ECS services only after images, secrets, and migrations are ready."
  type        = bool
}
variable "build_sha" {
  description = "Git SHA or immutable build identifier included in runtime telemetry."
  type        = string
  default     = "unknown"
}
variable "otel_exporter_otlp_endpoint" {
  description = "Optional HTTPS OTLP trace endpoint; empty keeps tracing collector-free."
  type        = string
  default     = ""
  validation {
    condition     = var.otel_exporter_otlp_endpoint == "" || startswith(var.otel_exporter_otlp_endpoint, "https://")
    error_message = "otel_exporter_otlp_endpoint must be empty or HTTPS."
  }
}
variable "alarm_action_arns" {
  description = "Optional reviewed SNS/action ARNs for platform alarms."
  type        = list(string)
  default     = []
}
variable "quota_defaults" {
  description = "Non-secret deployment defaults for hosted operational capacity limits."
  type        = map(number)
  validation {
    condition = alltrue([
      for key in [
        "triage_per_hour", "concurrent_triage", "document_count", "document_bytes",
        "active_aws_integrations", "alerts_per_hour", "concurrent_index_builds",
        "execution_intents_per_hour"
      ] : contains(keys(var.quota_defaults), key) && var.quota_defaults[key] > 0
    ])
    error_message = "quota_defaults must provide every positive hosted quota default."
  }
}
variable "api_image_digest" {
  type = string
  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.api_image_digest))
    error_message = "api_image_digest must be an immutable sha256 digest"
  }
}
variable "worker_image_digest" {
  type = string
  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.worker_image_digest))
    error_message = "worker_image_digest must be an immutable sha256 digest"
  }
}
variable "web_image_digest" {
  type = string
  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.web_image_digest))
    error_message = "web_image_digest must be an immutable sha256 digest"
  }
}
variable "api_cpu" { type = number }
variable "api_memory" { type = number }
variable "api_desired_count" { type = number }
variable "api_max_count" { type = number }
variable "worker_cpu" { type = number }
variable "worker_memory" { type = number }
variable "worker_desired_count" { type = number }
variable "worker_max_count" { type = number }
variable "dispatcher_desired_count" { type = number }
variable "web_cpu" { type = number }
variable "web_memory" { type = number }
variable "web_desired_count" { type = number }
variable "web_max_count" { type = number }
variable "database_instance_class" { type = string }
variable "database_allocated_storage" { type = number }
variable "database_max_allocated_storage" { type = number }
variable "database_multi_az" { type = bool }
variable "database_backup_retention_days" { type = number }
variable "database_monitoring_interval" { type = number }
variable "database_name" { type = string }
variable "database_migration_username" { type = string }
variable "cognito_domain_prefix" { type = string }
variable "cognito_mfa_configuration" { type = string }
variable "cognito_callback_urls" { type = list(string) }
variable "cognito_logout_urls" { type = list(string) }
variable "customer_role_path_prefix" {
  type    = string
  default = "aira-read/"
}
variable "allowed_eventbridge_source_accounts" {
  description = "Accounts allowed to PutEvents on the central bus; empty denies cross-account delivery."
  type        = set(string)
  default     = []
}
variable "tags" {
  type    = map(string)
  default = {}
}
