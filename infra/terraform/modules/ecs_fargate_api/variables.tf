variable "name_prefix" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "subnet_ids" {
  type        = list(string)
  description = "Public subnets for Fargate tasks (assign_public_ip=true for OpenAI egress without NAT)"
}

variable "ecs_security_group_ids" {
  type = list(string)
}

variable "target_group_arn" {
  type = string
}

variable "container_image" {
  type        = string
  description = "Full image URI e.g. 123.dkr.ecr.us-east-1.amazonaws.com/aira-dev-api:latest"
}

variable "container_port" {
  type    = number
  default = 8000
}

variable "cpu" {
  type    = number
  default = 256
}

variable "memory" {
  type    = number
  default = 512
}

variable "desired_count" {
  type    = number
  default = 1
}

variable "log_retention_days" {
  type    = number
  default = 7
}

variable "environment_variables" {
  type = list(object({ name = string, value = string }))
  default = [
    { name = "API_HOST", value = "0.0.0.0" },
    { name = "API_PORT", value = "8000" },
    { name = "ENABLE_GRADIO_UI", value = "1" },
  ]
}

variable "container_secrets" {
  type        = list(object({ name = string, valueFrom = string }))
  default     = []
  description = "ECS secrets (e.g. OPENAI_API_KEY from SSM or Secrets Manager ARN)"
}

variable "ssm_parameter_arns_for_execution" {
  type        = list(string)
  default     = []
  description = "SSM parameter ARNs the execution role may read (must cover all valueFrom ARNs that are SSM)"
}

variable "enable_execute_command" {
  type    = bool
  default = false
}

variable "enable_container_insights" {
  type        = bool
  default     = false
  description = "Enable ECS Container Insights (extra CloudWatch cost; turn on for prod observability)"
}
