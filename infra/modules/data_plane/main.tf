terraform {
  required_version = ">= 1.16.5, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.68.0, < 7.0.0"
    }
  }
}

# INFRA-002 stage 3: data plane for the four Lambda function classes named in
# ARCHITECTURE 12.1 and 12.2 (API, restricted parser, general analysis worker,
# restricted execution worker). It creates ECR repositories, SQS queues with
# dead-letter queues, the private data bucket (quarantine, accepted and export
# prefixes), the private guest-demo publication bucket, log groups, and one
# execution role per function class. It creates no Lambda function, API
# Gateway, CloudFront, KMS key, database resource, interface endpoint or flow
# log. SSE uses AWS-owned keys (SSE-S3, SSE-SQS, AES256 for ECR).
#
# INFRA-008 Stage A adds two Secrets Manager secret containers (database-url,
# openai-api-key) with no value: no aws_secretsmanager_secret_version exists, so
# no secret value is in configuration, variables or state. The owner sets the
# values with the AWS CLI after apply (docs/INFRASTRUCTURE.md). Only the API and
# general roles may read them.

variable "name_prefix" {
  description = "Resource name prefix from the naming module."
  type        = string
}

variable "parser_function_timeout_seconds" {
  description = "Parser Lambda timeout; the parser has a hard 15-second limit (compose.yaml)."
  type        = number
  default     = 15

  validation {
    condition     = var.parser_function_timeout_seconds >= 1 && var.parser_function_timeout_seconds <= 15
    error_message = "The parser timeout must not exceed the 15-second parser limit."
  }
}

variable "general_function_timeout_seconds" {
  description = "General worker Lambda timeout (assumption until INFRA-002 stage 4 sets the function)."
  type        = number
  default     = 300
}

variable "execution_function_timeout_seconds" {
  description = "Executor Lambda timeout; one request of at most 30 seconds plus setup (execution_plans.py)."
  type        = number
  default     = 60

  validation {
    condition     = var.execution_function_timeout_seconds > 30
    error_message = "The executor timeout must exceed the 30-second maximum request timeout."
  }
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for every function log group (never 'never expire', per ADR-017)."
  type        = number
  default     = 14
}

variable "demo_cloudfront_distribution_arn" {
  description = "CloudFront distribution allowed to read demo publications through Origin Access Control (INFRA-002 stage 4); null for none."
  type        = string
  default     = null
}

variable "ecr_images_to_keep" {
  description = "Number of most recent images kept per ECR repository."
  type        = number
  default     = 5
}

data "aws_partition" "current" {}

locals {
  function_classes = ["api", "parser", "general", "executor"]

  # Lambda guidance: queue visibility timeout at least six times the function
  # timeout; maxReceiveCount at least 5.
  queues = {
    parser    = { visibility = 6 * var.parser_function_timeout_seconds }
    general   = { visibility = 6 * var.general_function_timeout_seconds }
    execution = { visibility = 6 * var.execution_function_timeout_seconds }
  }

  max_receive_count = 5
  # Standard-queue messages keep their original enqueue timestamp in the DLQ,
  # so the DLQ retention is longer than the source retention.
  source_retention_seconds = 345600  # 4 days
  dlq_retention_seconds    = 1209600 # 14 days (maximum)
}

# ---------------------------------------------------------------- ECR

resource "aws_ecr_repository" "function" {
  #checkov:skip=CKV_AWS_136:AES256 (AWS-owned key) encryption is deliberate; no customer managed KMS key with a monthly charge (ADR-017 cost target).
  for_each = toset(local.function_classes)

  name                 = "${var.name_prefix}-${each.key}"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "function" {
  for_each   = aws_ecr_repository.function
  repository = each.value.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the ${var.ecr_images_to_keep} most recent images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = var.ecr_images_to_keep
      }
      action = { type = "expire" }
    }]
  })
}

# ---------------------------------------------------------------- SQS

resource "aws_sqs_queue" "dlq" {
  for_each = local.queues

  name                      = "${var.name_prefix}-${each.key}-dlq"
  sqs_managed_sse_enabled   = true
  message_retention_seconds = local.dlq_retention_seconds
}

resource "aws_sqs_queue" "source" {
  for_each = local.queues

  name                       = "${var.name_prefix}-${each.key}"
  sqs_managed_sse_enabled    = true
  visibility_timeout_seconds = each.value.visibility
  message_retention_seconds  = local.source_retention_seconds
  receive_wait_time_seconds  = 20

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq[each.key].arn
    maxReceiveCount     = local.max_receive_count
  })
}

# Each DLQ accepts messages only from its own source queue.
resource "aws_sqs_queue_redrive_allow_policy" "dlq" {
  for_each  = local.queues
  queue_url = aws_sqs_queue.dlq[each.key].id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.source[each.key].arn]
  })
}

# ---------------------------------------------------------------- S3

# The values become S3 bucket Purpose tags. S3 accepts only Unicode letters,
# digits, white space and _ . : / = + @ - in tag values, and only the API
# checks this (the first apply failed with InvalidTag on parentheses and
# commas). References: data is ARCHITECTURE 10.2; demo is ADR-006, ADR-008
# and ADR-017.
locals {
  buckets = {
    data = "Private quarantine accepted-artifact and export objects"
    demo = "Private guest-demo publication snapshots"
  }
}

resource "aws_s3_bucket" "this" {
  #checkov:skip=CKV_AWS_145:SSE-S3 is deliberate; no customer managed KMS key with a monthly charge (ADR-017 cost target).
  #checkov:skip=CKV_AWS_18:No server access logging; it needs another bucket and log storage at portfolio scale. Revisit in HARD-001.
  #checkov:skip=CKV_AWS_144:No cross-Region replication; one Region (ADR-017) and versioning provide recovery at portfolio scale.
  #checkov:skip=CKV2_AWS_62:No S3 event notifications; uploads are announced through SQS by the API, not by bucket events.
  for_each = local.buckets

  bucket_prefix = "${var.name_prefix}-${each.key}-"

  tags = {
    Purpose = each.value
  }
}

resource "aws_s3_bucket_ownership_controls" "this" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.this[each.key].id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.this[each.key].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.this[each.key].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.this[each.key].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "this" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.this[each.key].id

  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.this]
}

data "aws_iam_policy_document" "tls_only" {
  for_each = local.buckets

  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.this[each.key].arn, "${aws_s3_bucket.this[each.key].arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  # Guest demo only: the CloudFront distribution may read publications/
  # through Origin Access Control. The fixed SourceArn keeps the policy
  # non-public, so Block Public Access stays on.
  dynamic "statement" {
    for_each = each.key == "demo" && var.demo_cloudfront_distribution_arn != null ? [var.demo_cloudfront_distribution_arn] : []

    content {
      sid       = "AllowCloudFrontOacReadPublications"
      effect    = "Allow"
      actions   = ["s3:GetObject"]
      resources = ["${aws_s3_bucket.this[each.key].arn}/publications/*"]

      principals {
        type        = "Service"
        identifiers = ["cloudfront.amazonaws.com"]
      }

      condition {
        test     = "StringEquals"
        variable = "AWS:SourceArn"
        values   = [statement.value]
      }
    }
  }
}

resource "aws_s3_bucket_policy" "tls_only" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.this[each.key].id
  policy   = data.aws_iam_policy_document.tls_only[each.key].json

  depends_on = [aws_s3_bucket_public_access_block.this]
}

# ---------------------------------------------------------------- Logs

resource "aws_cloudwatch_log_group" "function" {
  #checkov:skip=CKV_AWS_158:Log groups use the CloudWatch Logs default encryption; no customer managed KMS key with a monthly charge.
  #checkov:skip=CKV_AWS_338:Retention is deliberately short (log_retention_days, default 14) to control storage cost; a one-year retention is not required for this portfolio deployment.
  for_each = toset(local.function_classes)

  name              = "/aws/lambda/${var.name_prefix}-${each.key}"
  retention_in_days = var.log_retention_days
}

# ---------------------------------------------------------------- IAM

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "function" {
  for_each = toset(local.function_classes)

  name               = "${var.name_prefix}-${each.key}-lambda"
  description        = "Execution role for the ${each.key} Lambda function class"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

# All four function classes run in the VPC (ADR-017), so each needs the AWS
# managed policy that lets Lambda manage its network interfaces. That policy
# uses "Resource": "*" because the EC2 network-interface actions do not
# support resource-level permissions.
resource "aws_iam_role_policy_attachment" "vpc_access" {
  for_each   = aws_iam_role.function
  role       = each.value.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# ---------------------------------------------------------------- Secrets

locals {
  # Key = secret name suffix; the bootstrap reads the ARNs from
  # DATABASE_URL_SECRET_ARN and OPENAI_API_KEY_SECRET_ARN (secrets_bootstrap.py).
  application_secrets = {
    "database-url"   = "DATABASE_URL for the API and general worker: a PostgreSQL URL for the application database user (created in INFRA-012). Value set by the owner, never in Terraform."
    "openai-api-key" = "OPENAI_API_KEY for the API and general worker. Value set by the owner, never in Terraform."
  }
}

# Containers only. Encrypted with the AWS managed key aws/secretsmanager (no
# kms_key_id): a customer managed key is needed only for cross-account access
# and has a monthly charge. No Anthropic secret (ADR-018).
resource "aws_secretsmanager_secret" "application" {
  #checkov:skip=CKV_AWS_149:Encrypted with the AWS managed key aws/secretsmanager; a customer managed key is required only for cross-account access (none here) and has a monthly charge (ADR-017 cost target, ADR-018).
  #checkov:skip=CKV2_AWS_57:No automatic rotation in Stage A: rotation needs a rotation Lambda, the OpenAI key cannot be rotated by AWS, and the database-url value is a URL string, not the JSON a PostgreSQL rotation function expects. Rotation is manual (owner runbook); revisit in HARD-001.
  for_each = local.application_secrets

  name                    = "${var.name_prefix}/${each.key}"
  description             = each.value
  recovery_window_in_days = 30
}

# INFRA-008 Stage B (ADR-018 fallback): the parser's DATABASE_URL. A separate
# container, deliberately outside application_secrets, so the api and general
# roles cannot read it. No function role reads it: Terraform reads it at plan
# time into the parser's environment (compute_api), and only the migration
# runner may write it. No value here, no version, nothing in state from this
# resource.
resource "aws_secretsmanager_secret" "parser_database_url" {
  #checkov:skip=CKV_AWS_149:Encrypted with the AWS managed key aws/secretsmanager; a customer managed key is required only for cross-account access (none here) and has a monthly charge (ADR-017 cost target, ADR-018).
  #checkov:skip=CKV2_AWS_57:No automatic rotation: rotation needs a rotation Lambda and the value is a URL string, not the JSON a PostgreSQL rotation function expects. Rotation is manual (create_parser_user with rotate, then a re-apply); revisit in HARD-001.
  name                    = "${var.name_prefix}/parser-database-url"
  description             = "DATABASE_URL for the parser (ADR-018 fallback): a PostgreSQL URL for the restricted parser role, written by the migration runner. Value never in Terraform configuration."
  recovery_window_in_days = 30
}

locals {
  data_bucket_arn = aws_s3_bucket.this["data"].arn
  demo_bucket_arn = aws_s3_bucket.this["demo"].arn

  sqs_consume_actions = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]

  application_secret_arns = [for secret in aws_secretsmanager_secret.application : secret.arn]
}

data "aws_iam_policy_document" "api" {
  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.function["api"].arn}:*"]
  }

  statement {
    sid     = "EnqueueJobs"
    actions = ["sqs:SendMessage"]
    resources = [
      aws_sqs_queue.source["parser"].arn,
      aws_sqs_queue.source["general"].arn,
      aws_sqs_queue.source["execution"].arn,
    ]
  }

  statement {
    sid       = "WriteQuarantine"
    actions   = ["s3:PutObject"]
    resources = ["${local.data_bucket_arn}/quarantine/*"]
  }

  # Short-lived signed downloads after server-side authorization (ARCHITECTURE 10.2).
  statement {
    sid       = "ReadAcceptedAndExports"
    actions   = ["s3:GetObject"]
    resources = ["${local.data_bucket_arn}/accepted/*", "${local.data_bucket_arn}/exports/*"]
  }

  # An explicit owner action publishes a new immutable revision (ADR-006).
  statement {
    sid       = "PublishDemoRevision"
    actions   = ["s3:PutObject"]
    resources = ["${local.demo_bucket_arn}/publications/*"]
  }

  # Cold-start secret bootstrap (ADR-018, INFRA-008): the two exact ARNs only.
  statement {
    sid       = "ReadApplicationSecrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = local.application_secret_arns
  }
}

data "aws_iam_policy_document" "parser" {
  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.function["parser"].arn}:*"]
  }

  statement {
    sid       = "ConsumeParserQueue"
    actions   = local.sqs_consume_actions
    resources = [aws_sqs_queue.source["parser"].arn]
  }

  # No sqs:SendMessage: the parser never sends to the general queue. The
  # handoff stays in the database and the API sends the general wake-up
  # (ADR-018 option A, which removes this grant).

  statement {
    sid       = "ReadQuarantine"
    actions   = ["s3:GetObject"]
    resources = ["${local.data_bucket_arn}/quarantine/*"]
  }
}

data "aws_iam_policy_document" "general" {
  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.function["general"].arn}:*"]
  }

  statement {
    sid       = "ConsumeGeneralQueue"
    actions   = local.sqs_consume_actions
    resources = [aws_sqs_queue.source["general"].arn]
  }

  statement {
    sid       = "ReadWriteAcceptedAndExports"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${local.data_bucket_arn}/accepted/*", "${local.data_bucket_arn}/exports/*"]
  }

  # Cold-start secret bootstrap (ADR-018, INFRA-008): the two exact ARNs only.
  statement {
    sid       = "ReadApplicationSecrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = local.application_secret_arns
  }
}

data "aws_iam_policy_document" "executor" {
  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.function["executor"].arn}:*"]
  }

  statement {
    sid       = "ConsumeExecutionQueue"
    actions   = local.sqs_consume_actions
    resources = [aws_sqs_queue.source["execution"].arn]
  }
}

locals {
  role_policies = {
    api      = data.aws_iam_policy_document.api.json
    parser   = data.aws_iam_policy_document.parser.json
    general  = data.aws_iam_policy_document.general.json
    executor = data.aws_iam_policy_document.executor.json
  }
}

resource "aws_iam_role_policy" "function" {
  for_each = local.role_policies

  name   = "${var.name_prefix}-${each.key}-least-privilege"
  role   = aws_iam_role.function[each.key].id
  policy = each.value
}

# ---------------------------------------------------------------- Outputs

output "ecr_repository_urls" {
  description = "ECR repository URL per function class."
  value       = { for k, r in aws_ecr_repository.function : k => r.repository_url }
}

output "queue_arns" {
  description = "Source queue ARN per queue."
  value       = { for k, q in aws_sqs_queue.source : k => q.arn }
}

output "queue_urls" {
  description = "Source queue URL per queue."
  value       = { for k, q in aws_sqs_queue.source : k => q.id }
}

output "ecr_repositories" {
  description = "ECR repository name and ARN per function class."
  value       = { for k, r in aws_ecr_repository.function : k => { name = r.name, arn = r.arn } }
}

output "log_group_names" {
  description = "Log group name per function class."
  value       = { for k, g in aws_cloudwatch_log_group.function : k => g.name }
}

output "demo_bucket_regional_domain_name" {
  description = "Regional domain name of the guest-demo bucket (CloudFront origin)."
  value       = aws_s3_bucket.this["demo"].bucket_regional_domain_name
}

output "dlq_arns" {
  description = "Dead-letter queue ARN per queue."
  value       = { for k, q in aws_sqs_queue.dlq : k => q.arn }
}

output "data_bucket_name" {
  description = "Private data bucket (quarantine/, accepted/, exports/)."
  value       = aws_s3_bucket.this["data"].bucket
}

output "demo_bucket_name" {
  description = "Private guest-demo publication bucket (publications/)."
  value       = aws_s3_bucket.this["demo"].bucket
}

output "function_role_arns" {
  description = "Execution role ARN per function class."
  value       = { for k, r in aws_iam_role.function : k => r.arn }
}

output "application_secret_arns" {
  description = "ARNs (not values) of the database-url and openai-api-key secrets."
  value = {
    database_url   = aws_secretsmanager_secret.application["database-url"].arn
    openai_api_key = aws_secretsmanager_secret.application["openai-api-key"].arn
  }
}

output "parser_database_url_secret_arn" {
  description = "ARN (not value) of the parser-database-url secret."
  value       = aws_secretsmanager_secret.parser_database_url.arn
}

output "function_names" {
  description = "Function names the log groups and roles are prepared for (INFRA-002 stage 4)."
  value       = { for k in local.function_classes : k => "${var.name_prefix}-${k}" }
}
