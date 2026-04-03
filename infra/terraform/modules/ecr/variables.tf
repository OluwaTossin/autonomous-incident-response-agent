variable "name_prefix" {
  type        = string
  description = "Prefix for repository name"
}

variable "repository_name" {
  type        = string
  default     = ""
  description = "Override full repo name; default {name_prefix}-api"
}
