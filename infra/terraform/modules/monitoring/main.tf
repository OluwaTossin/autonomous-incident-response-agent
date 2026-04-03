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
        title   = "ALB — request volume & latency"
        period  = 300
        view    = "timeSeries"
        stacked = false
        metrics = [
          ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", var.alb_arn_suffix, "TargetGroup", var.target_group_arn_suffix, { "stat" = "Sum", "label" = "Requests (TG)" }],
          [".", "TargetResponseTime", ".", ".", ".", ".", { "stat" = "Average", "label" = "Target latency (avg s)", "yAxis" = "right" }],
        ]
        yAxis = { left = { min = 0 }, right = { min = 0 } }
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
        title   = "ALB — HTTP errors (target vs ELB)"
        period  = 300
        view    = "timeSeries"
        stacked = true
        metrics = [
          ["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", "LoadBalancer", var.alb_arn_suffix, "TargetGroup", var.target_group_arn_suffix, { "stat" = "Sum" }],
          ["...", "HTTPCode_Target_4XX_Count", ".", ".", ".", ".", { "stat" = "Sum" }],
          ["AWS/ApplicationELB", "HTTPCode_ELB_5XX_Count", "LoadBalancer", var.alb_arn_suffix, { "stat" = "Sum" }],
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
      y      = 6
      width  = 12
      height = 6
      properties = {
        region = var.aws_region
        title  = "ECS service — CPU & memory"
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
      y      = 12
      width  = 12
      height = 6
      properties = {
        region = var.aws_region
        title  = "Triage — completions & duration (from API logs)"
        period = 300
        view   = "timeSeries"
        metrics = [
          [local.metrics_ns, "TriageSuccessCount", { "stat" = "Sum", "label" = "success" }],
          [".", "TriageFailureCount", { "stat" = "Sum", "label" = "graph_error" }],
          [".", "TriageDurationMs", { "stat" = "Average", "label" = "duration_ms_avg", "yAxis" = "right" }],
        ]
        yAxis = { left = { min = 0 }, right = { min = 0 } }
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
