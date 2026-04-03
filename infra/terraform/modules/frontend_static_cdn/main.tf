data "aws_caller_identity" "current" {}

data "aws_cloudfront_cache_policy" "caching_optimized" {
  count = var.enable_cloudfront ? 1 : 0
  name  = "Managed-CachingOptimized"
}

data "aws_cloudfront_cache_policy" "caching_disabled" {
  count = var.enable_cloudfront ? 1 : 0
  name  = "Managed-CachingDisabled"
}

resource "aws_s3_bucket" "ui" {
  bucket = "${var.name_prefix}-triage-ui-${data.aws_caller_identity.current.account_id}"

  tags = {
    Name = "${var.name_prefix}-triage-ui"
  }
}

# CloudFront path: fully private bucket. S3-website path: allow a public read policy on objects.
resource "aws_s3_bucket_public_access_block" "ui" {
  bucket = aws_s3_bucket.ui.id

  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = var.enable_cloudfront
  restrict_public_buckets = var.enable_cloudfront
}

resource "aws_s3_bucket_versioning" "ui" {
  bucket = aws_s3_bucket.ui.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "ui" {
  bucket = aws_s3_bucket.ui.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# --- Optional CloudFront (requires verified AWS account) ---

resource "aws_cloudfront_origin_access_control" "ui" {
  count = var.enable_cloudfront ? 1 : 0

  name                              = "${var.name_prefix}-ui-oac"
  description                       = "OAC for Next.js static export (${var.name_prefix})"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

locals {
  s3_origin_id = "s3-ui-${var.name_prefix}"
}

resource "aws_cloudfront_distribution" "ui" {
  count = var.enable_cloudfront ? 1 : 0

  enabled             = true
  is_ipv6_enabled     = true
  comment             = "${var.name_prefix} incident triage UI (S3 static)"
  default_root_object = "index.html"
  price_class         = var.price_class

  origin {
    domain_name              = aws_s3_bucket.ui.bucket_regional_domain_name
    origin_id                = local.s3_origin_id
    origin_access_control_id = aws_cloudfront_origin_access_control.ui[0].id
  }

  ordered_cache_behavior {
    path_pattern           = "/_next/static/*"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = local.s3_origin_id
    compress               = true
    viewer_protocol_policy = "redirect-to-https"
    cache_policy_id        = data.aws_cloudfront_cache_policy.caching_optimized[0].id
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = local.s3_origin_id
    compress               = true
    viewer_protocol_policy = "redirect-to-https"
    cache_policy_id        = data.aws_cloudfront_cache_policy.caching_disabled[0].id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  tags = {
    Name = "${var.name_prefix}-triage-ui-cf"
  }
}

resource "aws_s3_bucket_policy" "ui_cloudfront" {
  count  = var.enable_cloudfront ? 1 : 0
  bucket = aws_s3_bucket.ui.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowCloudFrontServicePrincipalReadOnly"
        Effect = "Allow"
        Principal = {
          Service = "cloudfront.amazonaws.com"
        }
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.ui.arn}/*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = aws_cloudfront_distribution.ui[0].arn
          }
        }
      }
    ]
  })
}

# --- S3 static website (no CloudFront) — HTTP website endpoint ---

resource "aws_s3_bucket_website_configuration" "ui" {
  count  = var.enable_cloudfront ? 0 : 1
  bucket = aws_s3_bucket.ui.id

  index_document {
    suffix = "index.html"
  }

  error_document {
    key = "index.html"
  }

  depends_on = [aws_s3_bucket_public_access_block.ui]
}

# Anonymous browser access needs Principal "*". That is blocked if either (1) this bucket still has
# block_public_policy=true, or (2) the account has S3 Block Public Access → "Block public bucket policies"
# enabled (Console: S3 → Block Public Access settings for this account). CloudFront mode avoids a
# public bucket policy once your account can create distributions.
resource "aws_s3_bucket_policy" "ui_public_read" {
  count  = var.enable_cloudfront ? 0 : 1
  bucket = aws_s3_bucket.ui.id

  depends_on = [aws_s3_bucket_public_access_block.ui]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "PublicReadGetObject"
        Effect    = "Allow"
        Principal = "*"
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.ui.arn}/*"
      }
    ]
  })
}
