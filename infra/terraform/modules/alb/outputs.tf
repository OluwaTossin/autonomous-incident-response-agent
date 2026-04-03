output "alb_arn" {
  value = aws_lb.this.arn
}

# CloudWatch ApplicationELB metrics dimension (e.g. app/aira-dev-alb/abc123)
output "alb_arn_suffix" {
  value = aws_lb.this.arn_suffix
}

# Target group dimension for ALB + TG combined metrics
output "target_group_arn_suffix" {
  value = aws_lb_target_group.api.arn_suffix
}

output "alb_dns_name" {
  value = aws_lb.this.dns_name
}

output "alb_zone_id" {
  value = aws_lb.this.zone_id
}

output "target_group_arn" {
  value = aws_lb_target_group.api.arn
}

output "listener_arn" {
  value = aws_lb_listener.http.arn
}
