resource "aws_cloudwatch_event_bus" "alerts" {
  name = "${local.name}-cloudwatch-alerts"
  tags = merge(local.common_tags, { component = "alert-ingestion" })
}
data "aws_iam_policy_document" "event_bus" {
  dynamic "statement" {
    for_each = var.allowed_eventbridge_source_accounts
    content {
      sid       = "AllowAccount${statement.value}"
      effect    = "Allow"
      actions   = ["events:PutEvents"]
      resources = [aws_cloudwatch_event_bus.alerts.arn]
      principals {
        type        = "AWS"
        identifiers = ["arn:aws:iam::${statement.value}:root"]
      }
    }
  }
}
resource "aws_cloudwatch_event_bus_policy" "alerts" {
  count          = length(var.allowed_eventbridge_source_accounts) > 0 ? 1 : 0
  event_bus_name = aws_cloudwatch_event_bus.alerts.name
  policy         = data.aws_iam_policy_document.event_bus.json
}
resource "aws_cloudwatch_event_rule" "cloudwatch_alarms" {
  name           = "${local.name}-cloudwatch-alarms"
  event_bus_name = aws_cloudwatch_event_bus.alerts.name
  event_pattern = jsonencode({
    source        = ["aws.cloudwatch"]
    "detail-type" = ["CloudWatch Alarm State Change"]
    account       = tolist(var.allowed_eventbridge_source_accounts)
  })
  tags = merge(local.common_tags, { component = "alert-ingestion" })
}
resource "aws_iam_role" "eventbridge_alerts" {
  name               = "${local.name}-eventbridge-alerts"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "events.amazonaws.com" }, Action = "sts:AssumeRole" }] })
  tags               = merge(local.common_tags, { component = "alert-ingestion" })
}
data "aws_iam_policy_document" "eventbridge_alerts" {
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.alerts.arn]
  }
  statement {
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.platform.arn]
  }
}
resource "aws_iam_role_policy" "eventbridge_alerts" {
  name   = "send-alerts"
  role   = aws_iam_role.eventbridge_alerts.id
  policy = data.aws_iam_policy_document.eventbridge_alerts.json
}
resource "aws_cloudwatch_event_target" "alerts" {
  rule           = aws_cloudwatch_event_rule.cloudwatch_alarms.name
  event_bus_name = aws_cloudwatch_event_bus.alerts.name
  arn            = aws_sqs_queue.alerts.arn
  role_arn       = aws_iam_role.eventbridge_alerts.arn
  dead_letter_config {
    arn = aws_sqs_queue.alerts_dlq.arn
  }
  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 12
  }
}
data "aws_iam_policy_document" "alert_queue" {
  statement {
    sid       = "AllowEventBridgeDelivery"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.alerts.arn]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.cloudwatch_alarms.arn]
    }
  }
}
resource "aws_sqs_queue_policy" "alerts" {
  queue_url = aws_sqs_queue.alerts.id
  policy    = data.aws_iam_policy_document.alert_queue.json
}

data "aws_iam_policy_document" "alert_dlq" {
  statement {
    sid       = "AllowEventBridgeDLQ"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.alerts_dlq.arn]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.cloudwatch_alarms.arn]
    }
  }
}
resource "aws_sqs_queue_policy" "alerts_dlq" {
  queue_url = aws_sqs_queue.alerts_dlq.id
  policy    = data.aws_iam_policy_document.alert_dlq.json
}
