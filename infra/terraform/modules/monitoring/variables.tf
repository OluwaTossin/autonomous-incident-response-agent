variable "name_prefix" {
  type        = string
  description = "e.g. aira-dev — dashboard and alarm name prefix"
}

variable "aws_region" {
  type = string
}

variable "alb_arn_suffix" {
  type        = string
  description = "aws_lb … arn_suffix (LoadBalancer dimension)"
}

variable "target_group_arn_suffix" {
  type        = string
  description = "aws_lb_target_group … arn_suffix (TargetGroup dimension)"
}

variable "ecs_cluster_name" {
  type = string
}

variable "ecs_service_name" {
  type = string
}

variable "cloudwatch_log_group_name" {
  type        = string
  description = "ECS api log group (e.g. /ecs/aira-dev-api)"
}

variable "metric_namespace" {
  type        = string
  default     = null
  description = "Custom metric namespace for log-derived metrics; default name_prefix/API"
}

variable "create_dashboard" {
  type    = bool
  default = true
}

variable "alarm_actions" {
  type        = list(string)
  default     = []
  description = "SNS topic ARNs (or other alarm action ARNs) — optional"
}

variable "alb_target_5xx_threshold" {
  type        = number
  default     = 10
  description = "Alarm when sum of HTTP 5xx from targets exceeds this per evaluation period"
}

variable "alb_target_5xx_period_seconds" {
  type    = number
  default = 300
}

variable "alb_target_5xx_evaluation_periods" {
  type    = number
  default = 1
}

variable "unhealthy_hosts_threshold" {
  type    = number
  default = 1
}

variable "unhealthy_hosts_period_seconds" {
  type    = number
  default = 60
}

variable "unhealthy_hosts_evaluation_periods" {
  type    = number
  default = 2
}
