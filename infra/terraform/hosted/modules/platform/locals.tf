locals {
  name = "${var.application}-${var.environment}"
  azs  = { for index, az in var.availability_zones : az => index }
  common_tags = merge(var.tags, {
    application = var.application
    environment = var.environment
    managed_by  = "terraform"
  })
  force_destroy = var.environment == "dev" && var.force_destroy_nonproduction
  nat_azs = var.nat_gateway_mode == "per_az" ? local.azs : {
    (var.availability_zones[0]) = 0
  }
  endpoint_services = toset(["ecr.api", "ecr.dkr", "logs", "secretsmanager", "sqs", "sts"])
}
