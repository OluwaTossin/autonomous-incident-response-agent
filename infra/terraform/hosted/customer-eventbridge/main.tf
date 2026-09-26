locals {
  name_suffix = substr(replace(var.integration_id, "_", "-"), 0, 32)
  event_pattern = merge({
    source        = ["aws.cloudwatch"]
    "detail-type" = ["CloudWatch Alarm State Change"]
    }, length(var.alarm_name_prefixes) == 0 ? {} : {
    detail = {
      alarmName = [for prefix in var.alarm_name_prefixes : { prefix = prefix }]
    }
  })
}

resource "aws_cloudwatch_event_rule" "aira" {
  name          = "aira-cloudwatch-${local.name_suffix}"
  description   = "Forward bounded CloudWatch alarm state changes to AIRA"
  event_pattern = jsonencode(local.event_pattern)
}

resource "aws_iam_role" "forwarder" {
  name = "aira-eventbridge-${local.name_suffix}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "forwarder" {
  name = "put-aira-events"
  role = aws_iam_role.forwarder.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["events:PutEvents"]
      Resource = var.aira_event_bus_arn
    }]
  })
}

resource "aws_cloudwatch_event_target" "aira" {
  rule     = aws_cloudwatch_event_rule.aira.name
  arn      = var.aira_event_bus_arn
  role_arn = aws_iam_role.forwarder.arn
}

output "rule_arn" { value = aws_cloudwatch_event_rule.aira.arn }
output "forwarder_role_arn" { value = aws_iam_role.forwarder.arn }
