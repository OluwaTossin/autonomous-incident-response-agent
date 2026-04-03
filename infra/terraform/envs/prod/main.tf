data "aws_caller_identity" "current" {}

locals {
  name_prefix = "${var.project_name}-${var.environment}"
  account_id  = data.aws_caller_identity.current.account_id

  openai_ssm_entry = var.openai_api_key_ssm_parameter != "" ? [{ env_name = "OPENAI_API_KEY", parameter_name = var.openai_api_key_ssm_parameter }] : []

  merged_ssm_secrets = concat(local.openai_ssm_entry, var.ssm_secrets)

  ssm_parameter_arns_for_ecs = distinct([
    for s in local.merged_ssm_secrets :
    "arn:aws:ssm:${var.aws_region}:${local.account_id}:parameter${s.parameter_name}"
  ])

  container_secrets = [
    for s in local.merged_ssm_secrets : {
      name      = s.env_name
      valueFrom = "arn:aws:ssm:${var.aws_region}:${local.account_id}:parameter${s.parameter_name}"
    }
  ]

  task_environment = concat(
    [
      { name = "API_HOST", value = "0.0.0.0" },
      { name = "API_PORT", value = tostring(var.api_container_port) },
      { name = "AIRA_ENV", value = var.environment },
      { name = "ENABLE_GRADIO_UI", value = "1" },
    ],
    var.cors_origins != "" ? [{ name = "CORS_ORIGINS", value = var.cors_origins }] : [],
    var.extra_task_environment
  )
}

module "vpc" {
  source = "../../modules/vpc"

  name_prefix = local.name_prefix
  environment = var.environment
}

module "security_groups" {
  source = "../../modules/security_groups"

  name_prefix           = local.name_prefix
  vpc_id                = module.vpc.vpc_id
  alb_ingress_cidr_ipv4 = var.alb_ingress_cidr_ipv4
  api_container_port    = var.api_container_port
}

module "ecr" {
  source = "../../modules/ecr"

  name_prefix = local.name_prefix
}

data "aws_ecr_image" "api" {
  repository_name = module.ecr.repository_name
  image_tag       = "latest"
}

module "alb" {
  source = "../../modules/alb"

  name_prefix                = local.name_prefix
  vpc_id                     = module.vpc.vpc_id
  public_subnet_ids          = module.vpc.public_subnet_ids
  alb_security_group_ids     = [module.security_groups.alb_security_group_id]
  target_port                = var.api_container_port
  enable_deletion_protection = var.alb_enable_deletion_protection
}

module "ecs_fargate_api" {
  source = "../../modules/ecs_fargate_api"

  name_prefix            = local.name_prefix
  aws_region             = var.aws_region
  subnet_ids             = module.vpc.public_subnet_ids
  ecs_security_group_ids = [module.security_groups.ecs_tasks_security_group_id]
  target_group_arn       = module.alb.target_group_arn
  container_image        = "${module.ecr.repository_url}@${data.aws_ecr_image.api.image_digest}"
  container_port         = var.api_container_port
  cpu                    = var.api_cpu
  memory                 = var.api_memory
  desired_count          = var.api_desired_count
  log_retention_days     = var.log_retention_days

  environment_variables = local.task_environment
  container_secrets     = local.container_secrets

  ssm_parameter_arns_for_execution = local.ssm_parameter_arns_for_ecs

  enable_container_insights = var.enable_container_insights
  enable_execute_command    = var.enable_execute_command

  health_check_grace_period_seconds = var.ecs_health_check_grace_period_seconds

  depends_on = [module.alb, module.ecr]
}

check "unique_ssm_secret_env_names" {
  assert {
    condition     = length(local.merged_ssm_secrets) == length(distinct([for s in local.merged_ssm_secrets : s.env_name]))
    error_message = "Duplicate env_name among openai_api_key_ssm_parameter (OPENAI_API_KEY) and ssm_secrets — each ECS secret name must be unique."
  }
}
