output "alb_url" {
  description = "HTTP URL for the API (ALB)"
  value       = "http://${module.alb.alb_dns_name}"
}

output "alb_dns_name" {
  value = module.alb.alb_dns_name
}

output "ecr_repository_url" {
  description = "docker build … && docker tag … && docker push target"
  value       = module.ecr.repository_url
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
  description = "Set this parameter (SecureString) before tasks can call OpenAI"
  value       = local.openai_parameter_arn != "" ? local.openai_parameter_arn : "(not configured — set var.openai_api_key_ssm_parameter)"
}
