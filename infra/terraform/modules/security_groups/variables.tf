variable "name_prefix" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "alb_ingress_cidr_ipv4" {
  type        = string
  default     = "0.0.0.0/0"
  description = "CIDR allowed to reach the ALB (restrict in prod if needed)"
}

variable "api_container_port" {
  type    = number
  default = 8000
}
