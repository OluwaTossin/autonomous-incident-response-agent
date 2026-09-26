resource "aws_cloudwatch_metric_alarm" "target_unhealthy" {
  for_each            = { api = aws_lb_target_group.api.arn_suffix, web = aws_lb_target_group.web.arn_suffix }
  alarm_name          = "${local.name}-${each.key}-unhealthy-target"
  alarm_description   = "SEV1 ${each.key} has no healthy target; runbook docs/v3/runbooks/hosted-observability.md#api-or-web-unhealthy"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  metric_name         = "HealthyHostCount"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Minimum"
  threshold           = var.enable_runtime_services ? 1 : 0
  treat_missing_data  = var.enable_runtime_services ? "breaching" : "notBreaching"
  dimensions = {
    LoadBalancer = aws_lb.this.arn_suffix
    TargetGroup  = each.value
  }
  alarm_actions = var.alarm_action_arns
  ok_actions    = var.alarm_action_arns
  tags          = merge(local.common_tags, { component = each.key, severity = "sev1" })
}

resource "aws_cloudwatch_metric_alarm" "target_5xx" {
  for_each            = { api = aws_lb_target_group.api.arn_suffix, web = aws_lb_target_group.web.arn_suffix }
  alarm_name          = "${local.name}-${each.key}-target-5xx"
  alarm_description   = "SEV2 sustained ${each.key} target errors; runbook docs/v3/runbooks/hosted-observability.md#api-or-web-unhealthy"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"
  dimensions = {
    LoadBalancer = aws_lb.this.arn_suffix
    TargetGroup  = each.value
  }
  alarm_actions = var.alarm_action_arns
  ok_actions    = var.alarm_action_arns
  tags          = merge(local.common_tags, { component = each.key, severity = "sev2" })
}

resource "aws_cloudwatch_metric_alarm" "queue_age" {
  for_each = {
    jobs   = { name = aws_sqs_queue.jobs.name, threshold = 300, anchor = "job-queue-backlog" }
    alerts = { name = aws_sqs_queue.alerts.name, threshold = 120, anchor = "alert-ingestion-backlog-or-dlq" }
  }
  alarm_name          = "${local.name}-${each.key}-queue-age"
  alarm_description   = "SEV2 oldest ${each.key} message exceeds threshold; runbook docs/v3/runbooks/hosted-observability.md#${each.value.anchor}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  metric_name         = "ApproximateAgeOfOldestMessage"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Maximum"
  threshold           = each.value.threshold
  treat_missing_data  = "notBreaching"
  dimensions          = { QueueName = each.value.name }
  alarm_actions       = var.alarm_action_arns
  ok_actions          = var.alarm_action_arns
  tags                = merge(local.common_tags, { component = each.key, severity = "sev2" })
}

resource "aws_cloudwatch_metric_alarm" "worker_count" {
  for_each = {
    worker          = { service = aws_ecs_service.worker.name, desired = var.worker_desired_count, anchor = "worker-stalled" }
    dispatcher      = { service = aws_ecs_service.dispatcher.name, desired = var.dispatcher_desired_count, anchor = "dispatcher-stalled" }
    alert_ingestion = { service = aws_ecs_service.alert_ingestion.name, desired = 1, anchor = "alert-ingestion-backlog-or-dlq" }
  }
  alarm_name          = "${local.name}-${each.key}-task-count"
  alarm_description   = "SEV2 ${each.key} running below desired; runbook docs/v3/runbooks/hosted-observability.md#${each.value.anchor}"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  metric_name         = "RunningTaskCount"
  namespace           = "ECS/ContainerInsights"
  period              = 60
  statistic           = "Minimum"
  threshold           = var.enable_runtime_services ? each.value.desired : 0
  treat_missing_data  = var.enable_runtime_services ? "breaching" : "notBreaching"
  dimensions = {
    ClusterName = aws_ecs_cluster.this.name
    ServiceName = each.value.service
  }
  alarm_actions = var.alarm_action_arns
  ok_actions    = var.alarm_action_arns
  tags          = merge(local.common_tags, { component = each.key, severity = "sev2" })
}

resource "aws_cloudwatch_metric_alarm" "database_storage" {
  alarm_name          = "${local.name}-database-low-storage"
  alarm_description   = "SEV2 RDS free storage below 10 GiB; runbook docs/v3/runbooks/hosted-observability.md#rds-pressure-or-unavailable"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 3
  datapoints_to_alarm = 3
  metric_name         = "FreeStorageSpace"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Minimum"
  threshold           = 10737418240
  treat_missing_data  = "missing"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.postgres.identifier }
  alarm_actions       = var.alarm_action_arns
  ok_actions          = var.alarm_action_arns
  tags                = merge(local.common_tags, { component = "database", severity = "sev2" })
}

resource "aws_cloudwatch_metric_alarm" "database_memory" {
  alarm_name          = "${local.name}-database-low-memory"
  alarm_description   = "SEV3 RDS freeable memory below 256 MiB; runbook docs/v3/runbooks/hosted-observability.md#rds-pressure-or-unavailable"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 3
  datapoints_to_alarm = 3
  metric_name         = "FreeableMemory"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 268435456
  treat_missing_data  = "missing"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.postgres.identifier }
  alarm_actions       = var.alarm_action_arns
  ok_actions          = var.alarm_action_arns
  tags                = merge(local.common_tags, { component = "database", severity = "sev3" })
}

resource "aws_cloudwatch_metric_alarm" "outbox_publish_failure" {
  alarm_name          = "${local.name}-dispatcher-publish-failures"
  alarm_description   = "SEV2 dispatcher publish failures; runbook docs/v3/runbooks/hosted-observability.md#dispatcher-stalled"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  metric_name         = "outbox_publish_total"
  namespace           = "AIRA/Hosted"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  dimensions = {
    Environment = var.environment
    Service     = "dispatcher"
    Operation   = "outbox_publish"
    Result      = "failed"
  }
  alarm_actions = var.alarm_action_arns
  ok_actions    = var.alarm_action_arns
  tags          = merge(local.common_tags, { component = "dispatcher", severity = "sev2" })
}

resource "aws_cloudwatch_metric_alarm" "api_error_budget_fast" {
  alarm_name          = "${local.name}-api-slo-fast-burn"
  alarm_description   = "SEV1 API internal SLO fast burn; runbook docs/v3/runbooks/hosted-observability.md#api-error-budget-burn"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 12
  datapoints_to_alarm = 3
  threshold           = 0.0144
  treat_missing_data  = "notBreaching"
  metric_query {
    id          = "error_ratio"
    expression  = "IF(requests>0,errors/requests,0)"
    label       = "API error ratio"
    return_data = true
  }
  metric_query {
    id = "errors"
    metric {
      metric_name = "server_error_count"
      namespace   = "AIRA/Hosted"
      period      = 300
      stat        = "Sum"
      dimensions  = { Environment = var.environment, Service = "api" }
    }
  }
  metric_query {
    id = "requests"
    metric {
      metric_name = "eligible_request_count"
      namespace   = "AIRA/Hosted"
      period      = 300
      stat        = "Sum"
      dimensions  = { Environment = var.environment, Service = "api" }
    }
  }
  alarm_actions = var.alarm_action_arns
  ok_actions    = var.alarm_action_arns
  tags          = merge(local.common_tags, { component = "api", severity = "sev1" })
}

resource "aws_cloudwatch_metric_alarm" "api_error_budget_slow" {
  alarm_name          = "${local.name}-api-slo-slow-burn"
  alarm_description   = "SEV2 API internal SLO slow burn; runbook docs/v3/runbooks/hosted-observability.md#api-error-budget-burn"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 6
  datapoints_to_alarm = 3
  threshold           = 0.006
  treat_missing_data  = "notBreaching"
  metric_query {
    id          = "error_ratio"
    expression  = "IF(requests>0,errors/requests,0)"
    label       = "API error ratio"
    return_data = true
  }
  metric_query {
    id = "errors"
    metric {
      metric_name = "server_error_count"
      namespace   = "AIRA/Hosted"
      period      = 3600
      stat        = "Sum"
      dimensions  = { Environment = var.environment, Service = "api" }
    }
  }
  metric_query {
    id = "requests"
    metric {
      metric_name = "eligible_request_count"
      namespace   = "AIRA/Hosted"
      period      = 3600
      stat        = "Sum"
      dimensions  = { Environment = var.environment, Service = "api" }
    }
  }
  alarm_actions = var.alarm_action_arns
  ok_actions    = var.alarm_action_arns
  tags          = merge(local.common_tags, { component = "api", severity = "sev2" })
}
