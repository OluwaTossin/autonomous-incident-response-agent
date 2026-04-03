output "alb_url" {
  description = "HTTP URL for the API (add TLS in front for real prod)"
  value       = "http://${module.alb.alb_dns_name}"
}

output "alb_dns_name" {
  value = module.alb.alb_dns_name
}

output "ecr_repository_url" {
  value = module.ecr.repository_url
}

output "ecr_repository_name" {
  value = module.ecr.repository_name
}

output "ecs_cluster_name" {
  value = module.ecs_fargate_api.cluster_name
}

output "ecs_service_name" {
  value = module.ecs_fargate_api.service_name
}

output "cloudwatch_log_group" {
  value = module.ecs_fargate_api.log_group_name
}

output "openai_ssm_parameter_arn" {
  value = local.openai_parameter_arn != "" ? local.openai_parameter_arn : "(set var.openai_api_key_ssm_parameter)"
}
