output "s3_bucket_id" {
  description = "Bucket id for aws s3 sync"
  value       = aws_s3_bucket.ui.id
}

output "s3_bucket_arn" {
  value = aws_s3_bucket.ui.arn
}

output "enable_cloudfront" {
  value = var.enable_cloudfront
}

output "cloudfront_distribution_id" {
  description = "Empty when using S3 website only"
  value       = var.enable_cloudfront ? aws_cloudfront_distribution.ui[0].id : ""
}

output "ui_url" {
  description = "Open in browser — HTTPS (CloudFront) or HTTP (S3 website)"
  value       = var.enable_cloudfront ? "https://${aws_cloudfront_distribution.ui[0].domain_name}" : "http://${aws_s3_bucket_website_configuration.ui[0].website_endpoint}"
}

# Backward-compatible name for scripts/docs
output "cloudfront_url" {
  value = var.enable_cloudfront ? "https://${aws_cloudfront_distribution.ui[0].domain_name}" : "http://${aws_s3_bucket_website_configuration.ui[0].website_endpoint}"
}

output "s3_website_endpoint" {
  description = "Host only — same as embedded in ui_url when not using CloudFront"
  value       = var.enable_cloudfront ? "" : aws_s3_bucket_website_configuration.ui[0].website_endpoint
}
