resource "aws_ecr_repository" "service" {
  for_each             = toset(["api", "worker", "web"])
  name                 = "${local.name}-${each.value}"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = local.force_destroy
  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.platform.arn
  }
  tags = merge(local.common_tags, { component = each.value })
}
resource "aws_ecr_lifecycle_policy" "service" {
  for_each   = aws_ecr_repository.service
  repository = each.value.name
  policy     = jsonencode({ rules = [{ rulePriority = 1, description = "Retain the latest 30 immutable images", selection = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 30 }, action = { type = "expire" } }] })
}

resource "aws_secretsmanager_secret" "database_runtime" {
  name                    = "${local.name}/database/runtime-url"
  kms_key_id              = aws_kms_key.platform.arn
  recovery_window_in_days = var.environment == "prod" ? 30 : 7
  tags                    = merge(local.common_tags, { component = "database" })
}
resource "aws_secretsmanager_secret" "web_database" {
  name                    = "${local.name}/database/web-url"
  kms_key_id              = aws_kms_key.platform.arn
  recovery_window_in_days = var.environment == "prod" ? 30 : 7
  tags                    = merge(local.common_tags, { component = "database" })
}
resource "aws_secretsmanager_secret" "llm_provider" {
  name                    = "${local.name}/providers/llm-api-key"
  kms_key_id              = aws_kms_key.platform.arn
  recovery_window_in_days = var.environment == "prod" ? 30 : 7
  tags                    = merge(local.common_tags, { component = "api" })
}
resource "aws_secretsmanager_secret" "web_session" {
  name                    = "${local.name}/web/session-encryption-key"
  kms_key_id              = aws_kms_key.platform.arn
  recovery_window_in_days = var.environment == "prod" ? 30 : 7
  tags                    = merge(local.common_tags, { component = "web" })
}
resource "aws_secretsmanager_secret" "worker_scope_grants" {
  name                    = "${local.name}/worker/scope-grants"
  kms_key_id              = aws_kms_key.platform.arn
  recovery_window_in_days = var.environment == "prod" ? 30 : 7
  tags                    = merge(local.common_tags, { component = "worker" })
}

resource "aws_cloudwatch_log_group" "service" {
  for_each          = toset(["api", "worker", "dispatcher", "web", "migration", "alert-ingestion"])
  name              = "/aira/${var.environment}/${each.value}"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.platform.arn
  tags              = merge(local.common_tags, { component = each.value })
}

resource "aws_ecs_cluster" "this" {
  name = local.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
  tags = merge(local.common_tags, { component = "runtime" })
}

locals {
  execution_secret_arns = {
    api             = [aws_secretsmanager_secret.database_runtime.arn, aws_secretsmanager_secret.llm_provider.arn]
    worker          = [aws_secretsmanager_secret.database_runtime.arn, aws_secretsmanager_secret.llm_provider.arn, aws_secretsmanager_secret.worker_scope_grants.arn]
    dispatcher      = [aws_secretsmanager_secret.database_runtime.arn, aws_secretsmanager_secret.worker_scope_grants.arn]
    web             = [aws_secretsmanager_secret.web_database.arn, aws_secretsmanager_secret.web_session.arn]
    migration       = [aws_db_instance.postgres.master_user_secret[0].secret_arn, aws_secretsmanager_secret.database_runtime.arn]
    alert-ingestion = [aws_secretsmanager_secret.database_runtime.arn, aws_secretsmanager_secret.worker_scope_grants.arn]
  }
}

resource "aws_iam_role" "execution" {
  for_each           = local.execution_secret_arns
  name               = "${local.name}-${each.key}-execution"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }] })
  tags               = merge(local.common_tags, { component = "runtime" })
}
data "aws_iam_policy_document" "execution" {
  for_each = local.execution_secret_arns
  statement {
    sid       = "EcrAuthorization"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    sid       = "EcrPull"
    actions   = ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"]
    resources = [for repository in aws_ecr_repository.service : repository.arn]
  }
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.service[each.key].arn}:*"]
  }
  statement {
    sid       = "RuntimeSecrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = each.value
  }
  statement {
    sid       = "DecryptRuntimeSecrets"
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.platform.arn]
  }
}
resource "aws_iam_role_policy" "execution" {
  for_each = local.execution_secret_arns
  name     = "runtime-bootstrap"
  role     = aws_iam_role.execution[each.key].id
  policy   = data.aws_iam_policy_document.execution[each.key].json
}

resource "aws_iam_role" "api" {
  name               = "${local.name}-api"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }] })
  tags               = merge(local.common_tags, { component = "api" })
}
resource "aws_iam_role" "worker" {
  name               = "${local.name}-worker"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }] })
  tags               = merge(local.common_tags, { component = "worker" })
}
resource "aws_iam_role" "web" {
  name               = "${local.name}-web"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }] })
  tags               = merge(local.common_tags, { component = "web" })
}
resource "aws_iam_role" "dispatcher" {
  name               = "${local.name}-dispatcher"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }] })
  tags               = merge(local.common_tags, { component = "dispatcher" })
}
resource "aws_iam_role" "alert_ingestion" {
  name               = "${local.name}-alert-ingestion"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }] })
  tags               = merge(local.common_tags, { component = "alert-ingestion" })
}
resource "aws_iam_role" "migration" {
  name               = "${local.name}-migration"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }] })
  tags               = merge(local.common_tags, { component = "migration" })
}
resource "aws_iam_role" "customer_assumer" {
  name = "${local.name}-customer-read"
  path = "/aira/"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = [aws_iam_role.api.arn, aws_iam_role.worker.arn] }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = merge(local.common_tags, { component = "customer-context" })
}
data "aws_iam_policy_document" "assume_customer" {
  statement {
    sid       = "AssumeCustomerReadRoles"
    actions   = ["sts:AssumeRole"]
    resources = ["arn:aws:iam::*:role/${var.customer_role_path_prefix}*"]
  }
}
resource "aws_iam_role_policy" "customer_assumer" {
  name   = "assume-customer-read-roles"
  role   = aws_iam_role.customer_assumer.id
  policy = data.aws_iam_policy_document.assume_customer.json
}
data "aws_iam_policy_document" "assume_broker" {
  statement {
    actions   = ["sts:AssumeRole"]
    resources = [aws_iam_role.customer_assumer.arn]
  }
}
resource "aws_iam_role_policy" "api_assume_broker" {
  name   = "assume-customer-broker"
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.assume_broker.json
}
resource "aws_iam_role_policy" "worker_assume_broker" {
  name   = "assume-customer-broker"
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.assume_broker.json
}

data "aws_iam_policy_document" "api_data" {
  statement {
    sid       = "Documents"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.documents.arn}/*"]
  }
  statement {
    sid       = "DocumentList"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.documents.arn]
  }
  statement {
    sid       = "KnowledgeRead"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.knowledge.arn}/*"]
  }
  statement {
    sid       = "KnowledgeList"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.knowledge.arn]
  }
  statement {
    sid       = "KmsData"
    actions   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.platform.arn]
  }
}
resource "aws_iam_role_policy" "api_data" {
  name   = "hosted-data"
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api_data.json
}
data "aws_iam_policy_document" "worker_data" {
  statement {
    sid       = "JobQueue"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes", "sqs:SendMessage"]
    resources = [aws_sqs_queue.jobs.arn]
  }
  statement {
    sid       = "AlertQueue"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.alerts.arn]
  }
  statement {
    sid       = "Documents"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.documents.arn}/*"]
  }
  statement {
    sid       = "Knowledge"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.knowledge.arn}/*"]
  }
  statement {
    sid       = "BucketList"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.documents.arn, aws_s3_bucket.knowledge.arn]
  }
  statement {
    sid       = "KmsData"
    actions   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.platform.arn]
  }
}
resource "aws_iam_role_policy" "worker_data" {
  name   = "hosted-worker-data"
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.worker_data.json
}
data "aws_iam_policy_document" "dispatcher_data" {
  statement {
    sid       = "PublishJobs"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.jobs.arn]
  }
}
resource "aws_iam_role_policy" "dispatcher_data" {
  name   = "publish-jobs"
  role   = aws_iam_role.dispatcher.id
  policy = data.aws_iam_policy_document.dispatcher_data.json
}
data "aws_iam_policy_document" "alert_ingestion_data" {
  statement {
    sid       = "ConsumeAlerts"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.alerts.arn]
  }
}
resource "aws_iam_role_policy" "alert_ingestion_data" {
  name   = "consume-alerts"
  role   = aws_iam_role.alert_ingestion.id
  policy = data.aws_iam_policy_document.alert_ingestion_data.json
}

locals {
  api_environment = [
    { name = "AIRA_ENV", value = "production" },
    { name = "AIRA_BUILD_SHA", value = var.build_sha },
    { name = "AIRA_METRIC_NAMESPACE", value = "AIRA/Hosted" },
    { name = "AIRA_OTEL_EXPORTER_OTLP_ENDPOINT", value = var.otel_exporter_otlp_endpoint },
    { name = "AIRA_TRACE_SAMPLE_RATIO", value = var.environment == "prod" ? "0.05" : "1.0" },
    { name = "AIRA_AWS_REGION", value = var.aws_region },
    { name = "AIRA_SQS_QUEUE_URL", value = aws_sqs_queue.jobs.url },
    { name = "AIRA_ALERT_QUEUE_URL", value = aws_sqs_queue.alerts.url },
    { name = "AIRA_DOCUMENT_BUCKET", value = aws_s3_bucket.documents.id },
    { name = "AIRA_KNOWLEDGE_BUCKET", value = aws_s3_bucket.knowledge.id },
    { name = "AIRA_KMS_KEY_ARN", value = aws_kms_key.platform.arn },
    { name = "AIRA_OIDC_ISSUER", value = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.this.id}" },
    { name = "AIRA_OIDC_CLIENT_ID", value = aws_cognito_user_pool_client.web.id },
    { name = "AIRA_AWS_TRUSTED_PRINCIPAL_ARN", value = aws_iam_role.customer_assumer.arn },
    { name = "AIRA_AWS_SOURCE_ROLE_ARN", value = aws_iam_role.customer_assumer.arn },
    { name = "AIRA_PUBLIC_ORIGIN", value = "https://${var.web_hostname}" },
    { name = "AIRA_QUOTA_TRIAGE_PER_HOUR", value = tostring(var.quota_defaults.triage_per_hour) },
    { name = "AIRA_QUOTA_CONCURRENT_TRIAGE", value = tostring(var.quota_defaults.concurrent_triage) },
    { name = "AIRA_QUOTA_DOCUMENT_COUNT", value = tostring(var.quota_defaults.document_count) },
    { name = "AIRA_QUOTA_DOCUMENT_BYTES", value = tostring(var.quota_defaults.document_bytes) },
    { name = "AIRA_QUOTA_ACTIVE_AWS_INTEGRATIONS", value = tostring(var.quota_defaults.active_aws_integrations) },
    { name = "AIRA_QUOTA_ALERTS_PER_HOUR", value = tostring(var.quota_defaults.alerts_per_hour) },
    { name = "AIRA_QUOTA_CONCURRENT_INDEX_BUILDS", value = tostring(var.quota_defaults.concurrent_index_builds) },
    { name = "AIRA_QUOTA_EXECUTION_INTENTS_PER_HOUR", value = tostring(var.quota_defaults.execution_intents_per_hour) },
  ]
  api_secrets = [
    { name = "AIRA_DATABASE_URL", valueFrom = aws_secretsmanager_secret.database_runtime.arn },
    { name = "OPENAI_API_KEY", valueFrom = aws_secretsmanager_secret.llm_provider.arn },
  ]
  worker_environment = concat(local.api_environment, [
    { name = "AIRA_RUNTIME_ROLE", value = "worker" },
    { name = "AIRA_WORKLOAD_SUBJECT", value = aws_iam_role.worker.arn },
  ])
  worker_secrets = concat(local.api_secrets, [{ name = "AIRA_WORKER_SCOPE_GRANTS", valueFrom = aws_secretsmanager_secret.worker_scope_grants.arn }])
  bounded_worker_secrets = [
    { name = "AIRA_DATABASE_URL", valueFrom = aws_secretsmanager_secret.database_runtime.arn },
    { name = "AIRA_WORKER_SCOPE_GRANTS", valueFrom = aws_secretsmanager_secret.worker_scope_grants.arn },
  ]
  web_environment = [
    { name = "AIRA_ENV", value = "production" },
    { name = "AIRA_BUILD_SHA", value = var.build_sha },
    { name = "AIRA_WEB_APP_ORIGIN", value = "https://${var.web_hostname}" },
    { name = "AIRA_WEB_API_BASE_URL", value = "https://${var.api_hostname}" },
    { name = "AIRA_WEB_OIDC_ISSUER", value = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.this.id}" },
    { name = "AIRA_WEB_OIDC_DOMAIN", value = "https://${aws_cognito_user_pool_domain.this.domain}.auth.${var.aws_region}.amazoncognito.com" },
    { name = "AIRA_WEB_OIDC_CLIENT_ID", value = aws_cognito_user_pool_client.web.id },
    { name = "AIRA_WEB_OIDC_SCOPES", value = "openid email profile" },
  ]
  web_secrets = [
    { name = "AIRA_WEB_DATABASE_URL", valueFrom = aws_secretsmanager_secret.web_database.arn },
    { name = "AIRA_WEB_SESSION_ENCRYPTION_KEY", valueFrom = aws_secretsmanager_secret.web_session.arn },
  ]
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.execution["api"].arn
  task_role_arn            = aws_iam_role.api.arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
  container_definitions = jsonencode([{
    name                   = "api", image = "${aws_ecr_repository.service["api"].repository_url}@${var.api_image_digest}", essential = true,
    command                = ["python", "-m", "app.runtime.hosted", "api"],
    readonlyRootFilesystem = true, user = "10001", portMappings = [{ containerPort = 8000, protocol = "tcp" }],
    environment            = local.api_environment, secrets = local.api_secrets,
    healthCheck            = { command = ["CMD-SHELL", "curl -fsS http://127.0.0.1:8000/healthz || exit 1"], interval = 30, timeout = 5, retries = 3, startPeriod = 30 },
    linuxParameters        = { initProcessEnabled = true, capabilities = { drop = ["ALL"] } }, mountPoints = [], volumesFrom = [],
    logConfiguration       = { logDriver = "awslogs", options = { "awslogs-group" = aws_cloudwatch_log_group.service["api"].name, "awslogs-region" = var.aws_region, "awslogs-stream-prefix" = "ecs" } }
  }])
  tags = merge(local.common_tags, { component = "api" })
}
resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.name}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.worker_cpu
  memory                   = var.worker_memory
  execution_role_arn       = aws_iam_role.execution["worker"].arn
  task_role_arn            = aws_iam_role.worker.arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
  container_definitions = jsonencode([{
    name             = "worker", image = "${aws_ecr_repository.service["worker"].repository_url}@${var.worker_image_digest}", essential = true,
    command          = ["python", "-m", "app.runtime.hosted", "worker"], readonlyRootFilesystem = true, user = "10001",
    environment      = local.worker_environment, secrets = local.worker_secrets,
    linuxParameters  = { initProcessEnabled = true, capabilities = { drop = ["ALL"] } }, mountPoints = [{ sourceVolume = "cache", containerPath = "/tmp/aira-faiss-cache", readOnly = false }], volumesFrom = [],
    logConfiguration = { logDriver = "awslogs", options = { "awslogs-group" = aws_cloudwatch_log_group.service["worker"].name, "awslogs-region" = var.aws_region, "awslogs-stream-prefix" = "ecs" } }
  }])
  volume {
    name = "cache"
  }
  tags = merge(local.common_tags, { component = "worker" })
}
resource "aws_ecs_task_definition" "dispatcher" {
  family                   = "${local.name}-dispatcher"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution["dispatcher"].arn
  task_role_arn            = aws_iam_role.dispatcher.arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
  container_definitions = jsonencode([{
    name             = "dispatcher", image = "${aws_ecr_repository.service["worker"].repository_url}@${var.worker_image_digest}", essential = true,
    command          = ["python", "-m", "app.runtime.hosted", "dispatcher"], readonlyRootFilesystem = true, user = "10001",
    environment      = local.worker_environment, secrets = local.bounded_worker_secrets,
    linuxParameters  = { initProcessEnabled = true, capabilities = { drop = ["ALL"] } }, mountPoints = [], volumesFrom = [],
    logConfiguration = { logDriver = "awslogs", options = { "awslogs-group" = aws_cloudwatch_log_group.service["dispatcher"].name, "awslogs-region" = var.aws_region, "awslogs-stream-prefix" = "ecs" } }
  }])
  tags = merge(local.common_tags, { component = "dispatcher" })
}
resource "aws_ecs_task_definition" "web" {
  family                   = "${local.name}-web"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.web_cpu
  memory                   = var.web_memory
  execution_role_arn       = aws_iam_role.execution["web"].arn
  task_role_arn            = aws_iam_role.web.arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
  container_definitions = jsonencode([{
    name                   = "web", image = "${aws_ecr_repository.service["web"].repository_url}@${var.web_image_digest}", essential = true,
    readonlyRootFilesystem = true, user = "10001", portMappings = [{ containerPort = 3000, protocol = "tcp" }],
    environment            = local.web_environment, secrets = local.web_secrets,
    healthCheck            = { command = ["CMD-SHELL", "node -e \"fetch('http://127.0.0.1:3000/healthz').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))\""], interval = 30, timeout = 5, retries = 3, startPeriod = 20 },
    linuxParameters        = { initProcessEnabled = true, capabilities = { drop = ["ALL"] } }, mountPoints = [], volumesFrom = [],
    logConfiguration       = { logDriver = "awslogs", options = { "awslogs-group" = aws_cloudwatch_log_group.service["web"].name, "awslogs-region" = var.aws_region, "awslogs-stream-prefix" = "ecs" } }
  }])
  tags = merge(local.common_tags, { component = "web" })
}
resource "aws_ecs_task_definition" "migration" {
  family                   = "${local.name}-migration"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution["migration"].arn
  task_role_arn            = aws_iam_role.migration.arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
  container_definitions = jsonencode([{
    name    = "migration", image = "${aws_ecr_repository.service["api"].repository_url}@${var.api_image_digest}", essential = true,
    command = ["python", "-m", "app.runtime.migrate"], readonlyRootFilesystem = true, user = "10001",
    secrets = [
      { name = "AIRA_DB_MASTER_SECRET", valueFrom = aws_db_instance.postgres.master_user_secret[0].secret_arn },
      { name = "AIRA_DATABASE_URL", valueFrom = aws_secretsmanager_secret.database_runtime.arn },
    ],
    environment      = [{ name = "AIRA_ENV", value = "production" }], linuxParameters = { initProcessEnabled = true, capabilities = { drop = ["ALL"] } }, mountPoints = [], volumesFrom = [],
    logConfiguration = { logDriver = "awslogs", options = { "awslogs-group" = aws_cloudwatch_log_group.service["migration"].name, "awslogs-region" = var.aws_region, "awslogs-stream-prefix" = "ecs" } }
  }])
  tags = merge(local.common_tags, { component = "migration" })
}

resource "aws_ecs_task_definition" "alert_ingestion" {
  family                   = "${local.name}-alert-ingestion"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution["alert-ingestion"].arn
  task_role_arn            = aws_iam_role.alert_ingestion.arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
  container_definitions = jsonencode([{
    name             = "alert-ingestion", image = "${aws_ecr_repository.service["worker"].repository_url}@${var.worker_image_digest}", essential = true,
    command          = ["python", "-m", "app.runtime.hosted", "alert-ingestion"], readonlyRootFilesystem = true, user = "10001",
    environment      = local.worker_environment, secrets = local.bounded_worker_secrets,
    linuxParameters  = { initProcessEnabled = true, capabilities = { drop = ["ALL"] } }, mountPoints = [], volumesFrom = [],
    logConfiguration = { logDriver = "awslogs", options = { "awslogs-group" = aws_cloudwatch_log_group.service["alert-ingestion"].name, "awslogs-region" = var.aws_region, "awslogs-stream-prefix" = "ecs" } }
  }])
  tags = merge(local.common_tags, { component = "alert-ingestion" })
}

resource "aws_ecs_service" "api" {
  name                               = "api"
  cluster                            = aws_ecs_cluster.this.id
  task_definition                    = aws_ecs_task_definition.api.arn
  desired_count                      = var.enable_runtime_services ? var.api_desired_count : 0
  launch_type                        = "FARGATE"
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    subnets          = [for subnet in aws_subnet.application : subnet.id]
    security_groups  = [aws_security_group.api.id]
    assign_public_ip = false
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }
  health_check_grace_period_seconds = 60
  depends_on                        = [aws_lb_listener.https]
  tags                              = merge(local.common_tags, { component = "api" })
}
resource "aws_ecs_service" "web" {
  name                               = "web"
  cluster                            = aws_ecs_cluster.this.id
  task_definition                    = aws_ecs_task_definition.web.arn
  desired_count                      = var.enable_runtime_services ? var.web_desired_count : 0
  launch_type                        = "FARGATE"
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    subnets          = [for subnet in aws_subnet.application : subnet.id]
    security_groups  = [aws_security_group.web.id]
    assign_public_ip = false
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.web.arn
    container_name   = "web"
    container_port   = 3000
  }
  health_check_grace_period_seconds = 60
  depends_on                        = [aws_lb_listener.https]
  tags                              = merge(local.common_tags, { component = "web" })
}
resource "aws_ecs_service" "worker" {
  name                               = "worker"
  cluster                            = aws_ecs_cluster.this.id
  task_definition                    = aws_ecs_task_definition.worker.arn
  desired_count                      = var.enable_runtime_services ? var.worker_desired_count : 0
  launch_type                        = "FARGATE"
  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    subnets          = [for subnet in aws_subnet.application : subnet.id]
    security_groups  = [aws_security_group.worker.id]
    assign_public_ip = false
  }
  tags = merge(local.common_tags, { component = "worker" })
}
resource "aws_ecs_service" "dispatcher" {
  name                               = "dispatcher"
  cluster                            = aws_ecs_cluster.this.id
  task_definition                    = aws_ecs_task_definition.dispatcher.arn
  desired_count                      = var.enable_runtime_services ? var.dispatcher_desired_count : 0
  launch_type                        = "FARGATE"
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    subnets          = [for subnet in aws_subnet.application : subnet.id]
    security_groups  = [aws_security_group.worker.id]
    assign_public_ip = false
  }
  tags = merge(local.common_tags, { component = "dispatcher" })
}

resource "aws_ecs_service" "alert_ingestion" {
  name                               = "alert-ingestion"
  cluster                            = aws_ecs_cluster.this.id
  task_definition                    = aws_ecs_task_definition.alert_ingestion.arn
  desired_count                      = var.enable_runtime_services ? 1 : 0
  launch_type                        = "FARGATE"
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    subnets          = [for subnet in aws_subnet.application : subnet.id]
    security_groups  = [aws_security_group.worker.id]
    assign_public_ip = false
  }
  tags = merge(local.common_tags, { component = "alert-ingestion" })
}

resource "aws_appautoscaling_target" "service" {
  for_each           = var.enable_runtime_services ? { api = [aws_ecs_service.api.name, var.api_desired_count, var.api_max_count], web = [aws_ecs_service.web.name, var.web_desired_count, var.web_max_count], worker = [aws_ecs_service.worker.name, var.worker_desired_count, var.worker_max_count] } : {}
  max_capacity       = each.value[2]
  min_capacity       = each.value[1]
  resource_id        = "service/${aws_ecs_cluster.this.name}/${each.value[0]}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}
resource "aws_appautoscaling_policy" "cpu" {
  for_each           = aws_appautoscaling_target.service
  name               = "${local.name}-${each.key}-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = each.value.resource_id
  scalable_dimension = each.value.scalable_dimension
  service_namespace  = each.value.service_namespace
  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value = 60
  }
}
