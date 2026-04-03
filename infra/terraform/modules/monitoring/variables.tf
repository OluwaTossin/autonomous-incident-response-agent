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

# --- ALB p95 latency alarm (scaling / SLO signal) ---
variable "create_alb_latency_p95_alarm" {
  type        = bool
  default     = true
  description = "Alarm when target response time p95 exceeds threshold (seconds)"
}

variable "alb_latency_p95_threshold_seconds" {
  type        = number
  default     = 25
  description = "ALB TargetResponseTime p95 above this triggers alarm (POST /triage can be slow)"
}

variable "alb_latency_p95_period_seconds" {
  type    = number
  default = 300
}

variable "alb_latency_p95_evaluation_periods" {
  type    = number
  default = 2
}

# --- ECS CPU alarm (future scaling trigger) ---
variable "create_ecs_cpu_alarm" {
  type    = bool
  default = true
}

variable "ecs_cpu_alarm_threshold_percent" {
  type        = number
  default     = 85
  description = "ECS service Average CPUUtilization above this triggers alarm"
}

variable "ecs_cpu_alarm_period_seconds" {
  type    = number
  default = 300
}

variable "ecs_cpu_alarm_evaluation_periods" {
  type    = number
  default = 2
}

# --- Application triage graph wall time (log-derived metric) ---
variable "create_triage_duration_alarm" {
  type    = bool
  default = true
}

variable "triage_duration_alarm_max_ms" {
  type        = number
  default     = 120000
  description = "Maximum single triage duration_ms in period before alarm (default 2 min)"
}

variable "triage_duration_alarm_period_seconds" {
  type    = number
  default = 300
}

variable "triage_duration_alarm_evaluation_periods" {
  type    = number
  default = 1
}
