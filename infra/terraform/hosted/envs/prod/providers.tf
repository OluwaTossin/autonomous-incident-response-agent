terraform {
  required_version = ">= 1.6.0"
  backend "s3" {}
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.80, < 7.0"
    }
  }
}
provider "aws" {
  region = var.aws_region
  default_tags {
    tags = { application = "aira", environment = "prod", managed_by = "terraform" }
  }
}
