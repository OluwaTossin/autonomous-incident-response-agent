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
  description = "e.g. /aira/prod/openai_api_key"
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
