module "monitoring" {
  source = "../../modules/monitoring"

  name_prefix               = local.name_prefix
  aws_region                = var.aws_region
  alb_arn_suffix            = module.alb.alb_arn_suffix
  target_group_arn_suffix   = module.alb.target_group_arn_suffix
  ecs_cluster_name          = module.ecs_fargate_api.cluster_name
  ecs_service_name          = module.ecs_fargate_api.service_name
  cloudwatch_log_group_name = module.ecs_fargate_api.log_group_name
  create_dashboard          = var.observability_create_dashboard
  alarm_actions             = var.observability_alarm_sns_topic_arns
  alb_target_5xx_threshold  = var.observability_alb_target_5xx_threshold

  depends_on = [module.ecs_fargate_api, module.alb]
}
