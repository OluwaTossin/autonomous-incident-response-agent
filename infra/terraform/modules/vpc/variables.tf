variable "name_prefix" {
  type        = string
  description = "Resource name prefix (e.g. aira-dev)"
}

variable "environment" {
  type        = string
  description = "Environment label (dev | prod)"
}

variable "vpc_cidr" {
  type        = string
  default     = "10.0.0.0/16"
  description = "VPC IPv4 CIDR"
}

variable "public_subnet_count" {
  type        = number
  default     = 2
  description = "Number of public subnets across AZs (min 2 for ALB)"
}
