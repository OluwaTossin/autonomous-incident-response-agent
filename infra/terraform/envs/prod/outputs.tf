output "aws_region" {
  description = "Region this stack was applied in (use for aws CLI / ECR login)"
  value       = var.aws_region
}

output "alb_url" {
  description = "HTTP URL for the API (add TLS in front for real prod)"
  value       = "http://${module.alb.alb_dns_name}"
}

output "alb_dns_name" {
  value = module.alb.alb_dns_name
}

output "ecr_repository_url" {
  description = "ECR repository URL (ECS pins digest of :latest — see ecr_image_digest)"
  value       = module.ecr.repository_url
}

output "ecr_image_digest" {
  description = "Digest Terraform resolved for :latest at last apply (immutable ECS reference)"
  value       = data.aws_ecr_image.api.image_digest
}

output "ecr_image_uri" {
  description = "Full image reference used by ECS (repository@digest)"
  value       = "${module.ecr.repository_url}@${data.aws_ecr_image.api.image_digest}"
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

output "ssm_container_secrets" {
  description = "Create each parameter_name as SSM SecureString; ECS maps to environment_variable"
  value = [
    for s in local.merged_ssm_secrets : {
      environment_variable = s.env_name
      parameter_name       = s.parameter_name
      arn                  = "arn:aws:ssm:${var.aws_region}:${local.account_id}:parameter${s.parameter_name}"
    }
  ]
}

output "openai_ssm_parameter_arn" {
  description = "OpenAI key ARN when openai_api_key_ssm_parameter is set"
  value       = var.openai_api_key_ssm_parameter != "" ? "arn:aws:ssm:${var.aws_region}:${local.account_id}:parameter${var.openai_api_key_ssm_parameter}" : "(not configured — set openai_api_key_ssm_parameter and/or ssm_secrets)"
}

# Phase 12 — Next.js static export (S3 ± CloudFront)
output "triage_ui_s3_bucket_id" {
  description = "S3 bucket for static triage UI (`aws s3 sync` / deploy script)"
  value       = module.triage_ui_cdn.s3_bucket_id
}

output "triage_ui_cloudfront_distribution_id" {
  description = "Empty when enable_triage_ui_cloudfront is false"
  value       = module.triage_ui_cdn.cloudfront_distribution_id
}

output "triage_ui_url" {
  description = "Browser URL for the static triage UI (add to cors_origins for API CORS)"
  value       = module.triage_ui_cdn.ui_url
}
