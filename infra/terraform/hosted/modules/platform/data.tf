data "aws_iam_policy_document" "kms" {
  statement {
    sid       = "EnableAccountAdministration"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${var.aws_account_id}:root"]
    }
  }
  statement {
    sid = "AllowCloudWatchLogsEncryption"
    actions = [
      "kms:Decrypt",
      "kms:DescribeKey",
      "kms:Encrypt",
      "kms:GenerateDataKey*",
      "kms:ReEncrypt*",
    ]
    resources = ["*"]
    principals {
      type        = "Service"
      identifiers = ["logs.${var.aws_region}.amazonaws.com"]
    }
    condition {
      test     = "ArnLike"
      variable = "kms:EncryptionContext:aws:logs:arn"
      values   = ["arn:aws:logs:${var.aws_region}:${var.aws_account_id}:log-group:/aira/${var.environment}/*"]
    }
  }
}

resource "aws_kms_key" "platform" {
  description             = "${local.name} hosted data encryption"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy                  = data.aws_iam_policy_document.kms.json
  tags                    = merge(local.common_tags, { component = "encryption" })
}
resource "aws_kms_alias" "platform" {
  name          = "alias/${local.name}-hosted"
  target_key_id = aws_kms_key.platform.key_id
}

resource "aws_s3_bucket" "documents" {
  bucket_prefix = "${local.name}-documents-"
  force_destroy = local.force_destroy
  tags          = merge(local.common_tags, { component = "documents" })
}
resource "aws_s3_bucket" "knowledge" {
  bucket_prefix = "${local.name}-knowledge-"
  force_destroy = local.force_destroy
  tags          = merge(local.common_tags, { component = "knowledge" })
}
resource "aws_s3_bucket_public_access_block" "private" {
  for_each                = { documents = aws_s3_bucket.documents.id, knowledge = aws_s3_bucket.knowledge.id }
  bucket                  = each.value
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_ownership_controls" "owner_enforced" {
  for_each = { documents = aws_s3_bucket.documents.id, knowledge = aws_s3_bucket.knowledge.id }
  bucket   = each.value
  rule { object_ownership = "BucketOwnerEnforced" }
}
resource "aws_s3_bucket_versioning" "enabled" {
  for_each = { documents = aws_s3_bucket.documents.id, knowledge = aws_s3_bucket.knowledge.id }
  bucket   = each.value
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "kms" {
  for_each = { documents = aws_s3_bucket.documents.id, knowledge = aws_s3_bucket.knowledge.id }
  bucket   = each.value
  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.platform.arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }
}
resource "aws_s3_bucket_lifecycle_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
    noncurrent_version_expiration { noncurrent_days = 90 }
  }
}
resource "aws_s3_bucket_lifecycle_configuration" "knowledge" {
  bucket = aws_s3_bucket.knowledge.id
  rule {
    id     = "retain-versioned-bundles"
    status = "Enabled"
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
    noncurrent_version_transition {
      noncurrent_days = 30
      storage_class   = "STANDARD_IA"
    }
  }
}
data "aws_iam_policy_document" "bucket_tls" {
  for_each = { documents = aws_s3_bucket.documents.arn, knowledge = aws_s3_bucket.knowledge.arn }
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions   = ["s3:*"]
    resources = [each.value, "${each.value}/*"]
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}
resource "aws_s3_bucket_policy" "tls" {
  for_each = data.aws_iam_policy_document.bucket_tls
  bucket   = each.key == "documents" ? aws_s3_bucket.documents.id : aws_s3_bucket.knowledge.id
  policy   = each.value.json
}

resource "aws_sqs_queue" "jobs_dlq" {
  name                      = "${local.name}-jobs-dlq"
  message_retention_seconds = 1209600
  kms_master_key_id         = aws_kms_key.platform.arn
  tags                      = merge(local.common_tags, { component = "jobs" })
}
resource "aws_sqs_queue" "jobs" {
  name                       = "${local.name}-jobs"
  visibility_timeout_seconds = 900
  receive_wait_time_seconds  = 20
  message_retention_seconds  = 345600
  kms_master_key_id          = aws_kms_key.platform.arn
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.jobs_dlq.arn
    maxReceiveCount     = 5
  })
  tags = merge(local.common_tags, { component = "jobs" })
}
resource "aws_sqs_queue_redrive_allow_policy" "jobs" {
  queue_url = aws_sqs_queue.jobs_dlq.id
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.jobs.arn]
  })
}

resource "aws_sqs_queue" "alerts_dlq" {
  name                      = "${local.name}-alerts-dlq"
  message_retention_seconds = 1209600
  kms_master_key_id         = aws_kms_key.platform.arn
  tags                      = merge(local.common_tags, { component = "alert-ingestion" })
}
resource "aws_sqs_queue" "alerts" {
  name                       = "${local.name}-alerts"
  visibility_timeout_seconds = 120
  receive_wait_time_seconds  = 20
  message_retention_seconds  = 345600
  kms_master_key_id          = aws_kms_key.platform.arn
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.alerts_dlq.arn
    maxReceiveCount     = 8
  })
  tags = merge(local.common_tags, { component = "alert-ingestion" })
}

resource "aws_db_subnet_group" "this" {
  name       = "${local.name}-database"
  subnet_ids = [for subnet in aws_subnet.database : subnet.id]
  tags       = merge(local.common_tags, { component = "database" })
}
resource "aws_iam_role" "rds_monitoring" {
  name               = "${local.name}-rds-monitoring"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "monitoring.rds.amazonaws.com" }, Action = "sts:AssumeRole" }] })
  tags               = merge(local.common_tags, { component = "database" })
}
resource "aws_iam_role_policy_attachment" "rds_monitoring" {
  role       = aws_iam_role.rds_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}
resource "aws_db_instance" "postgres" {
  identifier                      = "${local.name}-postgres"
  engine                          = "postgres"
  engine_version                  = "16.6"
  instance_class                  = var.database_instance_class
  allocated_storage               = var.database_allocated_storage
  max_allocated_storage           = var.database_max_allocated_storage
  storage_type                    = "gp3"
  storage_encrypted               = true
  kms_key_id                      = aws_kms_key.platform.arn
  db_name                         = var.database_name
  username                        = var.database_migration_username
  manage_master_user_password     = true
  master_user_secret_kms_key_id   = aws_kms_key.platform.key_id
  port                            = 5432
  publicly_accessible             = false
  multi_az                        = var.database_multi_az
  db_subnet_group_name            = aws_db_subnet_group.this.name
  vpc_security_group_ids          = [aws_security_group.database.id]
  parameter_group_name            = aws_db_parameter_group.postgres.name
  backup_retention_period         = var.database_backup_retention_days
  backup_window                   = "02:00-03:00"
  maintenance_window              = "sun:03:30-sun:04:30"
  auto_minor_version_upgrade      = true
  deletion_protection             = var.enable_deletion_protection
  skip_final_snapshot             = !var.enable_deletion_protection
  final_snapshot_identifier       = var.enable_deletion_protection ? "${local.name}-final" : null
  copy_tags_to_snapshot           = true
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]
  monitoring_interval             = var.database_monitoring_interval
  monitoring_role_arn             = var.database_monitoring_interval > 0 ? aws_iam_role.rds_monitoring.arn : null
  performance_insights_enabled    = true
  performance_insights_kms_key_id = aws_kms_key.platform.arn
  tags                            = merge(local.common_tags, { component = "database" })
}

resource "aws_db_parameter_group" "postgres" {
  name_prefix = "${local.name}-postgres-"
  family      = "postgres16"
  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
  tags = merge(local.common_tags, { component = "database" })
}
