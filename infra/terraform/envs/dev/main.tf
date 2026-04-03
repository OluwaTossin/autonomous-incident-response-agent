data "aws_caller_identity" "current" {}

locals {
  name_prefix = "${var.project_name}-${var.environment}"

  openai_parameter_arn = var.openai_api_key_ssm_parameter != "" ? "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.openai_api_key_ssm_parameter}" : ""

  container_secrets = var.openai_api_key_ssm_parameter != "" ? [
    {
      name      = "OPENAI_API_KEY"
      valueFrom = local.openai_parameter_arn
    }
  ] : []

  task_environment = concat(
    [
      { name = "API_HOST", value = "0.0.0.0" },
      { name = "API_PORT", value = tostring(var.api_container_port) },
      { name = "ENABLE_GRADIO_UI", value = "1" },
    ],
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
  container_image        = "${module.ecr.repository_url}:latest"
  container_port         = var.api_container_port
  cpu                    = var.api_cpu
  memory                 = var.api_memory
  desired_count          = var.api_desired_count
  log_retention_days     = var.log_retention_days

  environment_variables = local.task_environment
  container_secrets     = local.container_secrets

  ssm_parameter_arns_for_execution = local.openai_parameter_arn != "" ? [local.openai_parameter_arn] : []

  enable_container_insights = var.enable_container_insights
  enable_execute_command    = var.enable_execute_command

  depends_on = [module.alb]
}
