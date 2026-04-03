variable "aws_region" {
  type        = string
  description = "AWS region"
}

variable "project_name" {
  type    = string
  default = "aira"
}

variable "environment" {
  type    = string
  default = "prod"
}

variable "alb_ingress_cidr_ipv4" {
  type        = string
  default     = "0.0.0.0/0"
  description = "Prefer restricting to CloudFront or corporate egress in real prod"
}

variable "alb_enable_deletion_protection" {
  type    = bool
  default = true
}

variable "api_container_port" {
  type    = number
  default = 8000
}

variable "api_cpu" {
  type    = number
  default = 512
}

variable "api_memory" {
  type    = number
  default = 1024
}

variable "api_desired_count" {
  type    = number
  default = 2
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "openai_api_key_ssm_parameter" {
  type        = string
  default     = ""
  description = "Optional shorthand for OPENAI_API_KEY → SSM path. Prefer ssm_secrets for multiple keys."
  validation {
    condition     = var.openai_api_key_ssm_parameter == "" || startswith(var.openai_api_key_ssm_parameter, "/")
    error_message = "openai_api_key_ssm_parameter must be empty or a path starting with /."
  }
}

variable "ssm_secrets" {
  type = list(object({
    env_name       = string
    parameter_name = string
  }))
  default     = []
  description = "SSM SecureString parameters injected as container environment variables."
  validation {
    condition = alltrue([
      for s in var.ssm_secrets :
      startswith(s.parameter_name, "/") && length(s.env_name) > 0
    ])
    error_message = "Each ssm_secrets.parameter_name must start with / and env_name must be non-empty."
  }
}

variable "extra_task_environment" {
  type = list(object({ name = string, value = string }))
  default = [
    { name = "LLM_MODEL", value = "gpt-4o-mini" },
    { name = "EMBEDDING_MODEL", value = "text-embedding-3-small" },
  ]
}

variable "enable_container_insights" {
  type    = bool
  default = true
}

variable "enable_execute_command" {
  type    = bool
  default = false
}

variable "ecs_health_check_grace_period_seconds" {
  type        = number
  default     = 90
  description = "ALB target health ignored briefly after task start (see ECS service)"
}

variable "cors_origins" {
  type        = string
  default     = ""
  description = "Comma-separated browser origins allowed for CORS (Phase 12 triage UI). Injected as CORS_ORIGINS on the API task. Include triage_ui_url from terraform output after UI deploy."
}

variable "enable_triage_ui_cloudfront" {
  type        = bool
  default     = false
  description = "If true, private S3 + CloudFront (HTTPS). If false, S3 static website (HTTP) — for accounts where CloudFront is not yet enabled."
}
