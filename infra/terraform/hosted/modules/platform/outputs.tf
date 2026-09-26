output "web_url" { value = "https://${var.web_hostname}" }
output "api_url" { value = "https://${var.api_hostname}" }
output "alb_dns_name" { value = aws_lb.this.dns_name }
output "ecr_repository_urls" { value = { for name, repository in aws_ecr_repository.service : name => repository.repository_url } }
output "ecs_cluster_name" { value = aws_ecs_cluster.this.name }
output "ecs_service_names" {
  value = {
    api             = aws_ecs_service.api.name
    web             = aws_ecs_service.web.name
    worker          = aws_ecs_service.worker.name
    dispatcher      = aws_ecs_service.dispatcher.name
    alert_ingestion = aws_ecs_service.alert_ingestion.name
  }
}
output "migration_task_definition_arn" { value = aws_ecs_task_definition.migration.arn }
output "private_application_subnet_ids" { value = [for subnet in aws_subnet.application : subnet.id] }
output "worker_security_group_id" { value = aws_security_group.worker.id }
output "database_endpoint" { value = aws_db_instance.postgres.endpoint }
output "database_master_secret_arn" {
  value     = aws_db_instance.postgres.master_user_secret[0].secret_arn
  sensitive = true
}
output "runtime_secret_arns" {
  value = {
    database_url = aws_secretsmanager_secret.database_runtime.arn
    web_database = aws_secretsmanager_secret.web_database.arn
    llm_provider = aws_secretsmanager_secret.llm_provider.arn
    web_session  = aws_secretsmanager_secret.web_session.arn
    cursor_key   = aws_secretsmanager_secret.cursor_signing.arn
    worker_scope = aws_secretsmanager_secret.worker_scope_grants.arn
  }
}
output "job_queue_arn" { value = aws_sqs_queue.jobs.arn }
output "job_dlq_arn" { value = aws_sqs_queue.jobs_dlq.arn }
output "alert_queue_arn" { value = aws_sqs_queue.alerts.arn }
output "alert_dlq_arn" { value = aws_sqs_queue.alerts_dlq.arn }
output "document_bucket_name" { value = aws_s3_bucket.documents.id }
output "knowledge_bucket_name" { value = aws_s3_bucket.knowledge.id }
output "kms_key_arn" { value = aws_kms_key.platform.arn }
output "cognito_issuer" { value = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.this.id}" }
output "cognito_client_id" { value = aws_cognito_user_pool_client.web.id }
output "cognito_domain" { value = "https://${aws_cognito_user_pool_domain.this.domain}.auth.${var.aws_region}.amazoncognito.com" }
output "customer_assume_role_principal_arn" { value = aws_iam_role.customer_assumer.arn }
output "eventbridge_bus_arn" { value = aws_cloudwatch_event_bus.alerts.arn }
output "eventbridge_bus_name" { value = aws_cloudwatch_event_bus.alerts.name }
output "observability_dashboard_names" {
  value = {
    platform          = aws_cloudwatch_dashboard.platform.dashboard_name
    async             = aws_cloudwatch_dashboard.async.dashboard_name
    incident_pipeline = aws_cloudwatch_dashboard.incident_pipeline.dashboard_name
    control_plane     = aws_cloudwatch_dashboard.control_plane.dashboard_name
  }
}
