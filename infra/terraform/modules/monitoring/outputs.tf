output "dashboard_name" {
  description = "CloudWatch dashboard for ALB + ECS + triage log metrics"
  value       = one(aws_cloudwatch_dashboard.api[*].dashboard_name)
}

output "alarm_target_5xx_name" {
  value = aws_cloudwatch_metric_alarm.alb_target_5xx.alarm_name
}

output "alarm_unhealthy_targets_name" {
  value = aws_cloudwatch_metric_alarm.alb_unhealthy_targets.alarm_name
}

output "custom_metric_namespace" {
  value = local.metrics_ns
}

output "alarm_alb_latency_p95_name" {
  value = try(aws_cloudwatch_metric_alarm.alb_target_latency_p95_high[0].alarm_name, null)
}

output "alarm_ecs_cpu_high_name" {
  value = try(aws_cloudwatch_metric_alarm.ecs_cpu_high[0].alarm_name, null)
}

output "alarm_triage_duration_max_name" {
  value = try(aws_cloudwatch_metric_alarm.triage_duration_max_high[0].alarm_name, null)
}
