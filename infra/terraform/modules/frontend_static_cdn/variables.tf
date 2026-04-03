variable "name_prefix" {
  type        = string
  description = "e.g. aira-dev — used in bucket name and CloudFront comment"
}

variable "price_class" {
  type        = string
  default     = "PriceClass_100"
  description = "CloudFront price class (only when enable_cloudfront = true)"
}

variable "enable_cloudfront" {
  type        = bool
  default     = false
  description = "If false, use S3 static website hosting (HTTP) — for accounts where CloudFront is not yet enabled. If true, private S3 + CloudFront (HTTPS)."
}
