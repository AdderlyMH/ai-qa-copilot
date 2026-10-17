terraform {
  required_version = ">= 1.16.5, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.68.0, < 7.0.0"
    }
  }
}

# INFRA-012: the one-shot migration runner. A Lambda function from the
# "migrate" image target (apps/api/Dockerfile.lambda, handler
# ai_qa_copilot_api.lambda_migrate.handler) that the owner invokes manually
# with the AWS CLI. No HTTP API, event source mapping or schedule.
#
# The ECR repository is always created, so the owner can push the image before
# turning the runner on. The log group, role, policy and function exist only
# while migration_enabled is true (default false).
#
# The role may read the RDS-managed master secret and write a new version of
# the database-url secret, and nothing else besides its own log group and the
# VPC network-interface policy. No other function role can read the master
# secret.

# ---------------------------------------------------------------- Inputs

variable "name_prefix" {
  description = "Resource name prefix from the naming module."
  type        = string
}

variable "migration_enabled" {
  description = "Create the log group, role and function. Keep false except while the owner runs migrations."
  type        = bool
  default     = false
}

variable "image_uri" {
  description = "migrate image in this module's ECR repository, by digest (<repository URL>@sha256:<digest>). Required when migration_enabled is true."
  type        = string
  default     = null

  validation {
    condition     = var.image_uri == null || (can(regex("@sha256:[0-9a-f]{64}$", var.image_uri)) && !can(regex("@sha256:0{64}$", var.image_uri)))
    error_message = "image_uri must end in @sha256:<64 hex digits> and must not be the all-zero example digest."
  }
}

variable "subnet_id" {
  description = "Egress-compute subnet (route to the NAT instance for Secrets Manager)."
  type        = string
}

variable "security_group_id" {
  description = "egress_compute security group (TCP 5432 to the database group, TCP 443 out)."
  type        = string
}

variable "db_host" {
  description = "Database endpoint address (not a secret)."
  type        = string
}

variable "db_port" {
  description = "Database port."
  type        = number
}

variable "db_name" {
  description = "Application database name."
  type        = string
}

variable "master_secret_arn" {
  description = "ARN of the RDS-managed master user secret; the runner may read it."
  type        = string
}

variable "database_url_secret_arn" {
  description = "ARN of the database-url secret; the runner may write new versions only."
  type        = string
}

variable "app_db_user" {
  description = "Name of the non-superuser application database role the runner creates."
  type        = string
  default     = "ai_qa_copilot_app"

  validation {
    condition     = can(regex("^[a-z_][a-z0-9_]{0,62}$", var.app_db_user))
    error_message = "app_db_user must be a lower-case SQL identifier."
  }
}

variable "timeout_seconds" {
  description = "Function timeout; the Lambda maximum is 900 s."
  type        = number
  default     = 900

  validation {
    condition     = var.timeout_seconds >= 60 && var.timeout_seconds <= 900
    error_message = "timeout_seconds must be between 60 and 900."
  }
}

variable "memory_mb" {
  description = "Function memory in MB."
  type        = number
  default     = 1024
}

variable "log_retention_days" {
  description = "Retention of the runner's log group."
  type        = number
  default     = 14
}

variable "images_to_keep" {
  description = "Number of most recent images kept in the migrate repository."
  type        = number
  default     = 5
}

data "aws_partition" "current" {}
data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

locals {
  function_name = "${var.name_prefix}-migrate"
  enabled       = var.migration_enabled ? 1 : 0
}

# ---------------------------------------------------------------- ECR (not gated)

resource "aws_ecr_repository" "migrate" {
  #checkov:skip=CKV_AWS_136:AES256 (AWS-owned key) encryption is deliberate; no customer managed KMS key with a monthly charge (ADR-017 cost target), as for the four function repositories.
  name                 = local.function_name
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "migrate" {
  repository = aws_ecr_repository.migrate.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the ${var.images_to_keep} most recent images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = var.images_to_keep
      }
      action = { type = "expire" }
    }]
  })
}

# ---------------------------------------------------------------- Gated resources

data "aws_iam_policy_document" "ecr_lambda_pull" {
  statement {
    sid     = "LambdaImageRetrieval"
    effect  = "Allow"
    actions = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:sourceArn"
      values   = ["arn:${data.aws_partition.current.partition}:lambda:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:function:${local.function_name}"]
    }
  }
}

resource "aws_ecr_repository_policy" "lambda_pull" {
  count      = local.enabled
  repository = aws_ecr_repository.migrate.name
  policy     = data.aws_iam_policy_document.ecr_lambda_pull.json
}

resource "aws_cloudwatch_log_group" "migrate" {
  #checkov:skip=CKV_AWS_158:Log groups use the CloudWatch Logs default encryption; no customer managed KMS key with a monthly charge (as for the function log groups).
  #checkov:skip=CKV_AWS_338:Retention is deliberately short (log_retention_days, default 14) to control storage cost, as for the function log groups.
  count             = local.enabled
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = var.log_retention_days
}

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

resource "aws_iam_role" "migrate" {
  count              = local.enabled
  name               = "${local.function_name}-lambda"
  description        = "Execution role for the one-shot migration runner (INFRA-012)"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

# The function runs in the VPC, so it needs the AWS managed policy for its
# network interfaces (the EC2 actions do not support resource-level
# permissions), as the four function roles do.
resource "aws_iam_role_policy_attachment" "vpc_access" {
  count      = local.enabled
  role       = aws_iam_role.migrate[0].name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

data "aws_iam_policy_document" "migrate" {
  count = local.enabled

  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.migrate[0].arn}:*"]
  }

  # The master secret is encrypted with the AWS managed key aws/secretsmanager,
  # so no kms:Decrypt grant is needed.
  statement {
    sid       = "ReadMasterUserSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.master_secret_arn]
  }

  statement {
    sid       = "WriteDatabaseUrlSecret"
    actions   = ["secretsmanager:PutSecretValue"]
    resources = [var.database_url_secret_arn]
  }
}

resource "aws_iam_role_policy" "migrate" {
  count  = local.enabled
  name   = "${local.function_name}-least-privilege"
  role   = aws_iam_role.migrate[0].id
  policy = data.aws_iam_policy_document.migrate[0].json
}

resource "aws_lambda_function" "migrate" {
  #checkov:skip=CKV_AWS_50:X-Ray tracing is off, as for the four functions; the runner logs fixed events only.
  #checkov:skip=CKV_AWS_115:No reserved concurrency, as for the four functions (reduced new-account concurrency quota); overlapping runs are excluded by a PostgreSQL advisory lock.
  #checkov:skip=CKV_AWS_116:No DLQ: the function is invoked synchronously by the owner, who sees every error in the invoke response.
  #checkov:skip=CKV_AWS_173:Environment variables hold only non-secret settings (host, port, database name, role name and secret ARNs, never values) and use Lambda's default encryption; no customer managed KMS key.
  #checkov:skip=CKV_AWS_272:No code signing configuration yet, as for the four functions; images are immutable, scanned on push and deployed by digest (INFRA-005).
  count = local.enabled

  function_name = local.function_name
  description   = "One-shot Alembic migration runner and application-role setup (INFRA-012); invoked manually"
  role          = aws_iam_role.migrate[0].arn
  package_type  = "Image"
  image_uri     = var.image_uri
  architectures = ["arm64"]
  timeout       = var.timeout_seconds
  memory_size   = var.memory_mb

  vpc_config {
    subnet_ids         = [var.subnet_id]
    security_group_ids = [var.security_group_id]
  }

  environment {
    variables = {
      APP_ENV                 = "production"
      DB_HOST                 = var.db_host
      DB_PORT                 = tostring(var.db_port)
      DB_NAME                 = var.db_name
      MASTER_SECRET_ARN       = var.master_secret_arn
      DATABASE_URL_SECRET_ARN = var.database_url_secret_arn
      APP_DB_USER             = var.app_db_user
    }
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.migrate[0].name
  }

  lifecycle {
    precondition {
      condition     = var.image_uri != null && startswith(coalesce(var.image_uri, "-"), "${aws_ecr_repository.migrate.repository_url}@sha256:")
      error_message = "migration_enabled needs image_uri set to this module's repository URL followed by @sha256:<digest>."
    }
  }

  depends_on = [
    aws_ecr_repository_policy.lambda_pull,
    aws_iam_role_policy.migrate,
    aws_iam_role_policy_attachment.vpc_access,
  ]
}

# ---------------------------------------------------------------- Outputs

output "ecr_repository_url" {
  description = "URL of the migrate ECR repository (push target)."
  value       = aws_ecr_repository.migrate.repository_url
}

output "ecr_repository_name" {
  description = "Name of the migrate ECR repository."
  value       = aws_ecr_repository.migrate.name
}

output "function_name" {
  description = "Name of the runner function, or null while migration_enabled is false."
  value       = var.migration_enabled ? aws_lambda_function.migrate[0].function_name : null
}
