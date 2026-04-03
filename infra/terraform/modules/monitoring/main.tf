# Phase 13 — CloudWatch dashboard, alarms, and log-derived triage metrics.

locals {
  metrics_ns = coalesce(var.metric_namespace, "${var.name_prefix}/API")

  dashboard_widgets = [
    {
      type   = "metric"
      x      = 0
      y      = 0
      width  = 12
      height = 6
      properties = {
        region  = var.aws_region
        title   = "ALB — request rate (per minute)"
        period  = 60
        view    = "timeSeries"
        stacked = false
        metrics = [
          ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", var.alb_arn_suffix, "TargetGroup", var.target_group_arn_suffix, { "stat" = "Sum", "label" = "Requests/min (TG)" }],
        ]
        yAxis = { left = { min = 0 } }
      }
    },
    {
      type   = "metric"
      x      = 12
      y      = 0
      width  = 12
      height = 6
      properties = {
        region  = var.aws_region
        title   = "ALB — target latency (avg & p95, seconds)"
        period  = 300
        view    = "timeSeries"
        stacked = false
        metrics = [
          ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", var.alb_arn_suffix, "TargetGroup", var.target_group_arn_suffix, { "stat" = "Average", "label" = "avg" }],
          ["...", { "stat" = "p95", "label" = "p95" }],
        ]
        yAxis = { left = { min = 0 } }
      }
    },
    {
      type   = "metric"
      x      = 0
      y      = 6
      width  = 12
      height = 6
      properties = {
        region  = var.aws_region
        title   = "ALB — target 5xx & ELB 5xx (server errors)"
        period  = 300
        view    = "timeSeries"
        stacked = false
        metrics = [
          ["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", "LoadBalancer", var.alb_arn_suffix, "TargetGroup", var.target_group_arn_suffix, { "stat" = "Sum", "label" = "Target 5xx" }],
          ["AWS/ApplicationELB", "HTTPCode_ELB_5XX_Count", "LoadBalancer", var.alb_arn_suffix, { "stat" = "Sum", "label" = "ELB 5xx" }],
        ]
        yAxis = { left = { min = 0 } }
      }
    },
    {
      type   = "metric"
      x      = 12
      y      = 6
      width  = 12
      height = 6
      properties = {
        region  = var.aws_region
        title   = "ALB — target 4xx (client / validation errors)"
        period  = 300
        view    = "timeSeries"
        stacked = false
        metrics = [
          ["AWS/ApplicationELB", "HTTPCode_Target_4XX_Count", "LoadBalancer", var.alb_arn_suffix, "TargetGroup", var.target_group_arn_suffix, { "stat" = "Sum" }],
        ]
        yAxis = { left = { min = 0 } }
      }
    },
    {
      type   = "metric"
      x      = 0
      y      = 12
      width  = 12
      height = 6
      properties = {
        region = var.aws_region
        title  = "ALB — target health"
        period = 60
        view   = "timeSeries"
        metrics = [
          ["AWS/ApplicationELB", "HealthyHostCount", "LoadBalancer", var.alb_arn_suffix, "TargetGroup", var.target_group_arn_suffix, { "stat" = "Average" }],
          [".", "UnHealthyHostCount", ".", ".", ".", ".", { "stat" = "Maximum" }],
        ]
        yAxis = { left = { min = 0 } }
      }
    },
    {
      type   = "metric"
      x      = 12
      y      = 12
      width  = 12
      height = 6
      properties = {
        region = var.aws_region
        title  = "ECS service — CPU & memory (%)"
        period = 300
        view   = "timeSeries"
        metrics = [
          ["AWS/ECS", "CPUUtilization", "ServiceName", var.ecs_service_name, "ClusterName", var.ecs_cluster_name, { "stat" = "Average" }],
          [".", "MemoryUtilization", ".", ".", ".", ".", { "stat" = "Average" }],
        ]
        yAxis = { left = { min = 0, max = 100 } }
      }
    },
    {
      type   = "metric"
      x      = 0
      y      = 18
      width  = 12
      height = 6
      properties = {
        region  = var.aws_region
        title   = "Triage — outcomes & LLM tokens (from API logs)"
        period  = 300
        view    = "timeSeries"
        stacked = false
        metrics = [
          [local.metrics_ns, "TriageSuccessCount", { "stat" = "Sum", "label" = "success" }],
          [".", "TriageFailureCount", { "stat" = "Sum", "label" = "graph_error" }],
          [".", "TriageTokensTotal", { "stat" = "Sum", "label" = "tokens (sum)", "yAxis" = "right" }],
        ]
        yAxis = { left = { min = 0 }, right = { min = 0 } }
      }
    },
    {
      type   = "metric"
      x      = 12
      y      = 18
      width  = 12
      height = 6
      properties = {
        region  = var.aws_region
        title   = "Triage — duration ms (avg & p95, graph wall time)"
        period  = 300
        view    = "timeSeries"
        stacked = false
        metrics = [
          [local.metrics_ns, "TriageDurationMs", { "stat" = "Average", "label" = "avg_ms" }],
          ["...", { "stat" = "p95", "label" = "p95_ms" }],
        ]
        yAxis = { left = { min = 0 } }
      }
    },
  ]
}

resource "aws_cloudwatch_dashboard" "api" {
  count          = var.create_dashboard ? 1 : 0
  dashboard_name = "${var.name_prefix}-api-observability"

  dashboard_body = jsonencode({ widgets = local.dashboard_widgets })
}

resource "aws_cloudwatch_metric_alarm" "alb_target_5xx" {
  alarm_name          = "${var.name_prefix}-alb-target-5xx"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = var.alb_target_5xx_evaluation_periods
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = var.alb_target_5xx_period_seconds
  statistic           = "Sum"
  threshold           = var.alb_target_5xx_threshold
  treat_missing_data  = "notBreaching"
  alarm_description   = "ALB registered targets returned 5xx — check ECS tasks, app logs, and deploy health"

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
    TargetGroup  = var.target_group_arn_suffix
  }

  alarm_actions = var.alarm_actions
  ok_actions    = var.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "alb_unhealthy_targets" {
  alarm_name          = "${var.name_prefix}-alb-unhealthy-targets"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = var.unhealthy_hosts_evaluation_periods
  metric_name         = "UnHealthyHostCount"
  namespace           = "AWS/ApplicationELB"
  period              = var.unhealthy_hosts_period_seconds
  statistic           = "Maximum"
  threshold           = var.unhealthy_hosts_threshold
  treat_missing_data  = "notBreaching"
  alarm_description   = "At least one target is unhealthy — ALB cannot route to API tasks"

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
    TargetGroup  = var.target_group_arn_suffix
  }

  alarm_actions = var.alarm_actions
  ok_actions    = var.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "alb_target_latency_p95_high" {
  count               = var.create_alb_latency_p95_alarm ? 1 : 0
  alarm_name          = "${var.name_prefix}-alb-target-latency-p95-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = var.alb_latency_p95_evaluation_periods
  metric_name         = "TargetResponseTime"
  namespace           = "AWS/ApplicationELB"
  period              = var.alb_latency_p95_period_seconds
  extended_statistic  = "p95"
  threshold           = var.alb_latency_p95_threshold_seconds
  treat_missing_data  = "notBreaching"
  alarm_description   = "ALB p95 target response time high — triage/LLM slow or overloaded; consider scaling or model tuning"

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
    TargetGroup  = var.target_group_arn_suffix
  }

  alarm_actions = var.alarm_actions
  ok_actions    = var.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "ecs_cpu_high" {
  count               = var.create_ecs_cpu_alarm ? 1 : 0
  alarm_name          = "${var.name_prefix}-ecs-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = var.ecs_cpu_alarm_evaluation_periods
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = var.ecs_cpu_alarm_period_seconds
  statistic           = "Average"
  threshold           = var.ecs_cpu_alarm_threshold_percent
  treat_missing_data  = "notBreaching"
  alarm_description   = "ECS service CPU high — scale tasks or increase cpu in task definition"

  dimensions = {
    ClusterName = var.ecs_cluster_name
    ServiceName = var.ecs_service_name
  }

  alarm_actions = var.alarm_actions
  ok_actions    = var.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "triage_duration_max_high" {
  count               = var.create_triage_duration_alarm ? 1 : 0
  alarm_name          = "${var.name_prefix}-triage-duration-max-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = var.triage_duration_alarm_evaluation_periods
  metric_name         = "TriageDurationMs"
  namespace           = local.metrics_ns
  period              = var.triage_duration_alarm_period_seconds
  statistic           = "Maximum"
  threshold           = var.triage_duration_alarm_max_ms
  treat_missing_data  = "notBreaching"
  alarm_description   = "Single triage graph run exceeded duration threshold — LLM/RAG stall or cold start"

  alarm_actions = var.alarm_actions
  ok_actions    = var.alarm_actions
}

# JSON lines from the API container: {"event":"triage_metrics",...} (stdout; see app/api/metrics_log.py)
resource "aws_cloudwatch_log_metric_filter" "triage_success" {
  name           = "${var.name_prefix}-triage-success"
  log_group_name = var.cloudwatch_log_group_name
  pattern        = "{ $.event = \"triage_metrics\" && $.success = true }"

  metric_transformation {
    name      = "TriageSuccessCount"
    namespace = local.metrics_ns
    value     = "1"
  }
}

resource "aws_cloudwatch_log_metric_filter" "triage_failure" {
  name           = "${var.name_prefix}-triage-failure"
  log_group_name = var.cloudwatch_log_group_name
  pattern        = "{ $.event = \"triage_metrics\" && $.success = false }"

  metric_transformation {
    name      = "TriageFailureCount"
    namespace = local.metrics_ns
    value     = "1"
  }
}

resource "aws_cloudwatch_log_metric_filter" "triage_duration_ms" {
  name           = "${var.name_prefix}-triage-duration-ms"
  log_group_name = var.cloudwatch_log_group_name
  pattern        = "{ $.event = \"triage_metrics\" && $.success = true }"

  metric_transformation {
    name      = "TriageDurationMs"
    namespace = local.metrics_ns
    value     = "$.duration_ms"
  }
}

resource "aws_cloudwatch_log_metric_filter" "triage_tokens_total" {
  name           = "${var.name_prefix}-triage-tokens-total"
  log_group_name = var.cloudwatch_log_group_name
  pattern        = "{ $.event = \"triage_metrics\" && $.success = true && $.tokens_total >= 1 }"

  metric_transformation {
    name      = "TriageTokensTotal"
    namespace = local.metrics_ns
    value     = "$.tokens_total"
  }
}
