variable "aws_region" {
  type        = string
  description = "AWS region (match .env AWS_REGION)"
}

variable "project_name" {
  type        = string
  default     = "aira"
  description = "Short name prefix for resources"
}

variable "environment" {
  type        = string
  default     = "dev"
  description = "Environment name (dev | prod)"
}

variable "alb_ingress_cidr_ipv4" {
  type        = string
  default     = "0.0.0.0/0"
  description = "CIDR allowed to hit the public ALB"
}

variable "alb_enable_deletion_protection" {
  type    = bool
  default = false
}

variable "api_container_port" {
  type    = number
  default = 8000
}

variable "api_cpu" {
  type    = number
  default = 256
}

variable "api_memory" {
  type    = number
  default = 512
}

variable "api_desired_count" {
  type    = number
  default = 1
}

variable "log_retention_days" {
  type    = number
  default = 7
}

variable "openai_api_key_ssm_parameter" {
  type        = string
  default     = ""
  description = "SSM parameter name (leading /) e.g. /aira/dev/openai_api_key — create as SecureString before first stable deploy"
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
  default = false
}

variable "enable_execute_command" {
  type    = bool
  default = false
}
