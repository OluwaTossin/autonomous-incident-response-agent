resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${local.name}-alb-5xx"
  alarm_description   = "SEV2 sustained ALB failures; runbook docs/v3/runbooks/hosted-observability.md#api-or-web-unhealthy"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_ELB_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"
  dimensions          = { LoadBalancer = aws_lb.this.arn_suffix }
  alarm_actions       = var.alarm_action_arns
  ok_actions          = var.alarm_action_arns
  tags                = merge(local.common_tags, { component = "edge" })
}
resource "aws_cloudwatch_metric_alarm" "jobs_dlq" {
  alarm_name          = "${local.name}-jobs-dlq-visible"
  alarm_description   = "SEV2 durable job DLQ is non-empty; runbook docs/v3/runbooks/hosted-observability.md#job-dlq"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Maximum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  dimensions          = { QueueName = aws_sqs_queue.jobs_dlq.name }
  alarm_actions       = var.alarm_action_arns
  ok_actions          = var.alarm_action_arns
  tags                = merge(local.common_tags, { component = "jobs" })
}
resource "aws_cloudwatch_metric_alarm" "alerts_dlq" {
  alarm_name          = "${local.name}-alerts-dlq-visible"
  alarm_description   = "SEV2 alert DLQ is non-empty; runbook docs/v3/runbooks/hosted-observability.md#alert-ingestion-backlog-or-dlq"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Maximum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  dimensions          = { QueueName = aws_sqs_queue.alerts_dlq.name }
  alarm_actions       = var.alarm_action_arns
  ok_actions          = var.alarm_action_arns
  tags                = merge(local.common_tags, { component = "alert-ingestion" })
}
resource "aws_cloudwatch_metric_alarm" "database_cpu" {
  alarm_name          = "${local.name}-database-cpu"
  alarm_description   = "SEV3 sustained RDS CPU pressure; runbook docs/v3/runbooks/hosted-observability.md#rds-pressure-or-unavailable"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  treat_missing_data  = "missing"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.postgres.identifier }
  alarm_actions       = var.alarm_action_arns
  ok_actions          = var.alarm_action_arns
  tags                = merge(local.common_tags, { component = "database" })
}
