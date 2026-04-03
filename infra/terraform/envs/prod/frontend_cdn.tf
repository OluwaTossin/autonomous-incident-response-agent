# Phase 12 — static Next.js export → S3. CloudFront (HTTPS) optional; default is S3 website (HTTP).
# After apply: ./scripts/aws/deploy_frontend_cdn.sh prod

module "triage_ui_cdn" {
  source = "../../modules/frontend_static_cdn"

  name_prefix       = local.name_prefix
  enable_cloudfront = var.enable_triage_ui_cloudfront
}
