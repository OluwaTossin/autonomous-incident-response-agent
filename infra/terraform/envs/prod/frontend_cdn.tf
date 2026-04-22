# Phase 12 — static Next.js export → S3 + CloudFront (HTTPS) by default (see enable_triage_ui_cloudfront).
# After apply: ./scripts/aws/deploy_frontend_cdn.sh prod

module "triage_ui_cdn" {
  source = "../../modules/frontend_static_cdn"

  name_prefix       = local.name_prefix
  enable_cloudfront = var.enable_triage_ui_cloudfront
}
