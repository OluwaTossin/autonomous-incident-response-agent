variable "aws_region" {
  type    = string
  default = "eu-west-2"
}
variable "aws_account_id" { type = string }
variable "availability_zones" {
  type    = list(string)
  default = ["eu-west-2a", "eu-west-2b"]
}
variable "vpc_cidr" {
  type    = string
  default = "10.30.0.0/16"
}
variable "route53_zone_id" { type = string }
variable "web_hostname" { type = string }
variable "api_hostname" { type = string }
variable "cognito_domain_prefix" { type = string }
variable "api_image_digest" { type = string }
variable "worker_image_digest" { type = string }
variable "web_image_digest" { type = string }
variable "allowed_eventbridge_source_accounts" {
  type    = set(string)
  default = []
}
variable "enable_runtime_services" {
  type    = bool
  default = false
}
variable "tags" {
  type    = map(string)
  default = {}
}
