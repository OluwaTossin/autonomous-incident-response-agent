resource "aws_cloudwatch_dashboard" "platform" {
  dashboard_name = "${local.name}-platform-overview"
  dashboard_body = jsonencode({ widgets = [
    { type = "metric", x = 0, y = 0, width = 12, height = 6, properties = { title = "API and web requests/errors", region = var.aws_region, period = 300, metrics = [
      ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", aws_lb.this.arn_suffix],
      [".", "HTTPCode_Target_5XX_Count", ".", ".", "TargetGroup", aws_lb_target_group.api.arn_suffix],
      [".", ".", ".", ".", ".", aws_lb_target_group.web.arn_suffix],
      [".", "HTTPCode_ELB_5XX_Count", "LoadBalancer", aws_lb.this.arn_suffix],
      [".", "TargetConnectionErrorCount", ".", ".", "TargetGroup", aws_lb_target_group.api.arn_suffix],
      [".", ".", ".", ".", ".", aws_lb_target_group.web.arn_suffix],
    ] } },
    { type = "metric", x = 12, y = 0, width = 12, height = 6, properties = { title = "ALB target health and latency", region = var.aws_region, period = 300, metrics = flatten([for target in [aws_lb_target_group.api.arn_suffix, aws_lb_target_group.web.arn_suffix] : [["AWS/ApplicationELB", "HealthyHostCount", "LoadBalancer", aws_lb.this.arn_suffix, "TargetGroup", target], [".", "UnHealthyHostCount", ".", ".", ".", target], [".", "TargetResponseTime", ".", ".", ".", target]]]) } },
    { type = "metric", x = 0, y = 6, width = 24, height = 6, properties = { title = "RDS health", region = var.aws_region, period = 300, metrics = [for metric in ["CPUUtilization", "DatabaseConnections", "FreeableMemory", "FreeStorageSpace", "ReadLatency", "WriteLatency", "Deadlocks"] : ["AWS/RDS", metric, "DBInstanceIdentifier", aws_db_instance.postgres.identifier]] } },
    { type = "metric", x = 0, y = 12, width = 24, height = 6, properties = { title = "ECS capacity", region = var.aws_region, period = 300, metrics = flatten([for service in [aws_ecs_service.api.name, aws_ecs_service.web.name, aws_ecs_service.worker.name, aws_ecs_service.dispatcher.name, aws_ecs_service.alert_ingestion.name] : [["ECS/ContainerInsights", "RunningTaskCount", "ClusterName", aws_ecs_cluster.this.name, "ServiceName", service], [".", "DesiredTaskCount", ".", ".", ".", service], ["AWS/ECS", "CPUUtilization", "ClusterName", aws_ecs_cluster.this.name, "ServiceName", service], [".", "MemoryUtilization", ".", ".", ".", service]]]) } },
  ] })
}

resource "aws_cloudwatch_dashboard" "async" {
  dashboard_name = "${local.name}-async-processing"
  dashboard_body = jsonencode({ widgets = [
    { type = "metric", x = 0, y = 0, width = 24, height = 6, properties = { title = "Queue depth, flow, and age", region = var.aws_region, period = 60, metrics = flatten([for queue in [aws_sqs_queue.jobs.name, aws_sqs_queue.alerts.name] : [["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", queue], [".", "ApproximateNumberOfMessagesNotVisible", ".", queue], [".", "ApproximateAgeOfOldestMessage", ".", queue], [".", "NumberOfMessagesSent", ".", queue], [".", "NumberOfMessagesReceived", ".", queue]]]) } },
    { type = "metric", x = 0, y = 6, width = 12, height = 6, properties = { title = "Separate DLQs", region = var.aws_region, period = 300, metrics = [["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.jobs_dlq.name], [".", ".", ".", aws_sqs_queue.alerts_dlq.name]] } },
    { type = "metric", x = 12, y = 6, width = 12, height = 6, properties = { title = "Worker and dispatcher", region = var.aws_region, period = 300, metrics = [["AIRA/Hosted", "worker_job_total", "Environment", var.environment, "Service", "worker"], [".", "outbox_publish_total", ".", ".", ".", "dispatcher"], [".", "outbox_pending_count", ".", ".", ".", "dispatcher"], [".", "outbox_oldest_pending_age_seconds", ".", ".", ".", "dispatcher"]] } },
  ] })
}

resource "aws_cloudwatch_dashboard" "incident_pipeline" {
  dashboard_name = "${local.name}-incident-pipeline"
  dashboard_body = jsonencode({ widgets = [
    { type = "metric", x = 0, y = 0, width = 24, height = 8, properties = { title = "Alert, enrichment, and triage outcomes", region = var.aws_region, period = 300, metrics = [
      ["AIRA/Hosted", "alert_events_accepted_total", "Environment", var.environment, "Service", "alert-ingestion"],
      [".", "context_enrichment_succeeded_total", ".", ".", ".", "worker"],
      [".", "triage_succeeded_total", ".", ".", ".", "worker"],
      [".", "triage_failed_total", ".", ".", ".", "worker"],
      [".", "job_queue_delay_ms", ".", ".", ".", "worker"],
      [".", "context_items_collected", ".", ".", ".", "worker"],
      [".", "context_truncated_total", ".", ".", ".", "worker"],
    ] } },
  ] })
}

resource "aws_cloudwatch_dashboard" "control_plane" {
  dashboard_name = "${local.name}-control-plane"
  dashboard_body = jsonencode({ widgets = [
    { type = "metric", x = 0, y = 0, width = 24, height = 8, properties = { title = "Proposal, approval, and intent outcomes", region = var.aws_region, period = 300, metrics = [
      ["AIRA/Hosted", "action_proposals_created_total", "Environment", var.environment, "Service", "worker"],
      [".", "approval_approved_total", ".", ".", ".", "api"],
      [".", "approval_rejected_total", ".", ".", ".", "api"],
      [".", "execution_intents_prepared_total", ".", ".", ".", "api"],
    ] } },
  ] })
}
