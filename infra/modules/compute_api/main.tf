terraform {
  required_version = ">= 1.16.5, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.68.0, < 7.0.0"
    }
  }
}

# INFRA-002 stage 4: the four Lambda container functions (ADR-017: Arm, VPC),
# their SQS event source mappings, ECR pull policies, the HTTP API for the API
# function, the CloudFront distribution for the guest demo (ADR-006, ADR-008,
# ADR-017 static snapshot) and the Cognito user pool for the single owner.
# No secret is set anywhere: DATABASE_URL and model-provider keys are not
# configured here (INFRA-003, application secret-store work). No database,
# KMS key, interface endpoint, flow log, custom domain, ACM certificate or
# WAF is created.

# ---------------------------------------------------------------- Inputs

variable "name_prefix" {
  description = "Resource name prefix from the naming module."
  type        = string
}

variable "image_uris" {
  description = "Container image URI per function class (api, parser, general, executor). No default: images must be pushed before apply."
  type        = map(string)

  validation {
    condition     = toset(keys(var.image_uris)) == toset(["api", "parser", "general", "executor"])
    error_message = "image_uris must have exactly the keys api, parser, general and executor."
  }
}

variable "memory_mb" {
  description = "Memory per function class in MB."
  type        = map(number)
  default = {
    api      = 512
    parser   = 512
    general  = 1024
    executor = 512
  }
}

variable "timeouts_seconds" {
  description = "Timeout per function class; must match the data-plane visibility assumptions."
  type        = map(number)
  default = {
    api      = 29
    parser   = 15
    general  = 300
    executor = 60
  }

  validation {
    condition     = var.timeouts_seconds["api"] < 30 && var.timeouts_seconds["parser"] <= 15
    error_message = "The API timeout must stay under the 30-second HTTP API limit and the parser timeout within its 15-second limit."
  }
}

variable "egress_subnet_id" {
  description = "Egress-compute subnet for the API, general worker and executor."
  type        = string
}

variable "parser_subnet_id" {
  description = "Parser subnet (no internet route)."
  type        = string
}

variable "egress_compute_security_group_id" {
  description = "Security group of the API, general worker and executor."
  type        = string
}

variable "parser_security_group_id" {
  description = "Security group of the parser."
  type        = string
}

variable "role_arns" {
  description = "Execution role ARN per function class (data plane)."
  type        = map(string)
}

variable "log_group_names" {
  description = "Log group name per function class (data plane)."
  type        = map(string)
}

variable "queue_arns" {
  description = "Source queue ARN per queue (parser, general, execution)."
  type        = map(string)
}

variable "queue_urls" {
  description = "Source queue URL per queue (parser, general, execution)."
  type        = map(string)
}

variable "ecr_repositories" {
  description = "ECR repository name and ARN per function class."
  type        = map(object({ name = string, arn = string }))
}

variable "application_secret_arns" {
  description = "ARNs (not values) of the database-url and openai-api-key secrets from the data plane; read at cold start by the API and general worker (INFRA-008)."
  type = object({
    database_url   = string
    openai_api_key = string
  })
}

variable "data_bucket_name" {
  description = "Private data bucket name."
  type        = string
}

variable "demo_bucket_name" {
  description = "Private guest-demo bucket name."
  type        = string
}

variable "demo_bucket_regional_domain_name" {
  description = "Regional domain name of the guest-demo bucket."
  type        = string
}

variable "cognito_owner_subject" {
  description = "Cognito `sub` of the single owner user. Not a secret; set after the owner user exists (see the runbook)."
  type        = string

  validation {
    condition     = length(trimspace(var.cognito_owner_subject)) > 0
    error_message = "cognito_owner_subject must not be empty."
  }
}

variable "model_provider" {
  description = "Model provider for the general worker (openai or anthropic)."
  type        = string
  default     = "openai"

  validation {
    condition     = contains(["openai", "anthropic"], var.model_provider)
    error_message = "model_provider must be openai or anthropic."
  }
}

variable "executor_enabled" {
  description = "Enable the execution queue trigger and the executor's explicit enable flag. Off until SG-08 executor egress control exists (INFRA-004)."
  type        = bool
  default     = false
}

variable "worker_max_concurrency" {
  description = "Maximum concurrent invocations per SQS event source (minimum 2) to protect the budget and the database."
  type        = number
  default     = 2

  validation {
    condition     = var.worker_max_concurrency >= 2 && var.worker_max_concurrency <= 10
    error_message = "worker_max_concurrency must be between 2 and 10."
  }
}

variable "api_throttle_rate_per_second" {
  description = "HTTP API steady-state request rate limit for the default stage."
  type        = number
  default     = 5
}

variable "api_throttle_burst" {
  description = "HTTP API burst limit for the default stage."
  type        = number
  default     = 10
}

variable "api_log_retention_days" {
  description = "Retention for the HTTP API access log group."
  type        = number
  default     = 14
}

data "aws_partition" "current" {}
data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

locals {
  region     = data.aws_region.current.region
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition

  function_names = { for k in ["api", "parser", "general", "executor"] : k => "${var.name_prefix}-${k}" }

  cognito_issuer = "https://cognito-idp.${local.region}.amazonaws.com/${aws_cognito_user_pool.owner.id}"

  # Non-secret settings only. Queue URLs and bucket names are provided for the
  # Lambda adapters; the application does not read them yet (open item). The
  # API and general worker get the two secret ARNs; the values are read at cold
  # start (secrets_bootstrap.py) and never appear here. MODEL_PROVIDER stays
  # unset on the API (OpenAI default) and openai on the general worker.
  secret_arn_environment = {
    DATABASE_URL_SECRET_ARN   = var.application_secret_arns.database_url
    OPENAI_API_KEY_SECRET_ARN = var.application_secret_arns.openai_api_key
  }

  environment = {
    api = merge(local.secret_arn_environment, {
      APP_ENV                   = "production"
      COGNITO_ISSUER            = local.cognito_issuer
      COGNITO_CLIENT_ID         = aws_cognito_user_pool_client.web.id
      COGNITO_OWNER_SUBJECT     = var.cognito_owner_subject
      PARSER_QUEUE_URL          = var.queue_urls["parser"]
      GENERAL_QUEUE_URL         = var.queue_urls["general"]
      EXECUTION_QUEUE_URL       = var.queue_urls["execution"]
      DATA_BUCKET_NAME          = var.data_bucket_name
      DEMO_BUCKET_NAME          = var.demo_bucket_name
      LOCAL_AUTH_BYPASS_ENABLED = "false"
    })
    parser = {
      APP_ENV               = "production"
      PARSER_WORKER_ROLE    = "restricted-parser"
      PARSER_WORKER_NETWORK = "none"
      DATA_BUCKET_NAME      = var.data_bucket_name
    }
    general = merge(local.secret_arn_environment, {
      APP_ENV          = "production"
      MODEL_PROVIDER   = var.model_provider
      DATA_BUCKET_NAME = var.data_bucket_name
    })
    executor = {
      APP_ENV                                = "production"
      AI_QA_COPILOT_EXECUTION_WORKER_ENABLED = var.executor_enabled ? "true" : "false"
    }
  }

  vpc = {
    api      = { subnet = var.egress_subnet_id, sg = var.egress_compute_security_group_id }
    parser   = { subnet = var.parser_subnet_id, sg = var.parser_security_group_id }
    general  = { subnet = var.egress_subnet_id, sg = var.egress_compute_security_group_id }
    executor = { subnet = var.egress_subnet_id, sg = var.egress_compute_security_group_id }
  }

  queue_to_function = {
    parser    = "parser"
    general   = "general"
    execution = "executor"
  }
}

# ---------------------------------------------------------------- ECR pulls

# Same-account image pulls by the Lambda service, limited to this
# deployment's functions.
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
      values   = ["arn:${local.partition}:lambda:${local.region}:${local.account_id}:function:${var.name_prefix}-*"]
    }
  }
}

resource "aws_ecr_repository_policy" "lambda_pull" {
  for_each   = var.ecr_repositories
  repository = each.value.name
  policy     = data.aws_iam_policy_document.ecr_lambda_pull.json
}

# ---------------------------------------------------------------- Lambda

resource "aws_lambda_function" "this" {
  #checkov:skip=CKV_AWS_50:X-Ray tracing is off; ADR-011 structured tracing is application-level and X-Ray adds per-trace charges.
  #checkov:skip=CKV_AWS_115:No reserved concurrency; SQS event sources cap concurrency at 2 and the HTTP API is throttled, and reserving concurrency is not possible on accounts with the reduced new-account concurrency quota.
  #checkov:skip=CKV_AWS_116:No function DLQ; the functions are invoked synchronously (HTTP API, SQS event source mappings) and failed SQS messages go to the queue DLQs.
  #checkov:skip=CKV_AWS_173:Environment variables hold only non-secret settings (secret ARNs, never values; values come from Secrets Manager at cold start, INFRA-008) and use Lambda's default encryption; no customer managed KMS key.
  #checkov:skip=CKV_AWS_272:No code signing configuration yet; images are immutable, scanned on push and deployed by digest. Signing needs a signing profile and pipeline (INFRA-005).
  for_each = local.function_names

  function_name = each.value
  role          = var.role_arns[each.key]
  package_type  = "Image"
  image_uri     = var.image_uris[each.key]
  architectures = ["arm64"]
  timeout       = var.timeouts_seconds[each.key]
  memory_size   = var.memory_mb[each.key]

  vpc_config {
    subnet_ids         = [local.vpc[each.key].subnet]
    security_group_ids = [local.vpc[each.key].sg]
  }

  environment {
    variables = local.environment[each.key]
  }

  logging_config {
    log_format = "Text"
    log_group  = var.log_group_names[each.key]
  }

  depends_on = [aws_ecr_repository_policy.lambda_pull]
}

resource "aws_lambda_event_source_mapping" "worker" {
  for_each = local.queue_to_function

  event_source_arn        = var.queue_arns[each.key]
  function_name           = aws_lambda_function.this[each.value].arn
  batch_size              = 1
  function_response_types = ["ReportBatchItemFailures"]
  enabled                 = each.key == "execution" ? var.executor_enabled : true

  scaling_config {
    maximum_concurrency = var.worker_max_concurrency
  }
}

# ---------------------------------------------------------------- HTTP API

resource "aws_apigatewayv2_api" "http" {
  name          = "${var.name_prefix}-http"
  protocol_type = "HTTP"
  description   = "Owner and guest API; the function validates Cognito tokens itself (auth.py)."
}

resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.this["api"].invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 29000
}

resource "aws_apigatewayv2_route" "default" {
  #checkov:skip=CKV_AWS_309:No API Gateway authorizer: guest routes are anonymous by design (ADR-008) and the API function validates Cognito access tokens for owner routes (auth.py).
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

resource "aws_cloudwatch_log_group" "api_access" {
  #checkov:skip=CKV_AWS_158:Access logs use CloudWatch Logs default encryption; no customer managed KMS key.
  #checkov:skip=CKV_AWS_338:Retention is deliberately short (api_log_retention_days, default 14) to control storage cost.
  name              = "/aws/apigateway/${var.name_prefix}-http"
  retention_in_days = var.api_log_retention_days
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_rate_limit  = var.api_throttle_rate_per_second
    throttling_burst_limit = var.api_throttle_burst
  }

  # No headers, query strings or bodies are logged, so tokens never reach logs.
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_access.arn
    format = jsonencode({
      requestId      = "$context.requestId"
      requestTime    = "$context.requestTime"
      httpMethod     = "$context.httpMethod"
      routeKey       = "$context.routeKey"
      status         = "$context.status"
      responseLength = "$context.responseLength"
      integrationErr = "$context.integrationErrorMessage"
      latencyMs      = "$context.responseLatency"
    })
  }
}

resource "aws_lambda_permission" "http_api" {
  statement_id  = "AllowHttpApiInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.this["api"].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}

# ---------------------------------------------------------------- CloudFront

data "aws_cloudfront_cache_policy" "optimized" {
  name = "Managed-CachingOptimized"
}

data "aws_cloudfront_response_headers_policy" "security" {
  name = "Managed-SecurityHeadersPolicy"
}

resource "aws_cloudfront_origin_access_control" "demo" {
  name                              = "${var.name_prefix}-demo"
  description                       = "Guest-demo publications bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "demo" {
  #checkov:skip=CKV_AWS_68:No WAF in this stage (excluded by scope and cost); the origin is read-only static content behind OAC.
  #checkov:skip=CKV2_AWS_47:No WAF, so no Log4j managed rule; the origin serves static S3 objects only.
  #checkov:skip=CKV_AWS_86:No CloudFront access logging in this stage to avoid log storage; revisit in HARD-001.
  #checkov:skip=CKV_AWS_174:The default CloudFront certificate is used (no custom domain or ACM in this stage), which does not allow setting the minimum TLS version.
  #checkov:skip=CKV2_AWS_42:No custom certificate; custom domain and ACM are deferred.
  #checkov:skip=CKV_AWS_310:No origin failover; a single private S3 origin in one Region (ADR-017).
  #checkov:skip=CKV_AWS_374:No geo restriction; the public demo is intended to be reachable worldwide.
  enabled             = true
  comment             = "Guest demo: static DemoPublication snapshots (publications/ only)"
  default_root_object = "index.html"
  price_class         = "PriceClass_100"
  http_version        = "http2and3"
  is_ipv6_enabled     = true

  origin {
    origin_id                = "demo-publications"
    domain_name              = var.demo_bucket_regional_domain_name
    origin_path              = "/publications"
    origin_access_control_id = aws_cloudfront_origin_access_control.demo.id
  }

  default_cache_behavior {
    target_origin_id           = "demo-publications"
    viewer_protocol_policy     = "https-only"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = data.aws_cloudfront_cache_policy.optimized.id
    response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security.id
    compress                   = true
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

# ---------------------------------------------------------------- Cognito

resource "aws_cognito_user_pool" "owner" {
  name                = "${var.name_prefix}-owner"
  deletion_protection = "ACTIVE"
  username_attributes = ["email"]

  # One server-configured owner; no self sign-up (ADR-008).
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  password_policy {
    minimum_length                   = 14
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 3
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }
}

# Public client: no client secret. OAuth flows (authorization code with PKCE)
# need a user pool domain and HTTPS callback URLs, which are deferred.
resource "aws_cognito_user_pool_client" "web" {
  name                                 = "${var.name_prefix}-web"
  user_pool_id                         = aws_cognito_user_pool.owner.id
  generate_secret                      = false
  explicit_auth_flows                  = ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true
  allowed_oauth_flows_user_pool_client = false
  supported_identity_providers         = ["COGNITO"]
  access_token_validity                = 60
  id_token_validity                    = 60
  refresh_token_validity               = 12

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "hours"
  }
}

# ---------------------------------------------------------------- Outputs

output "http_api_endpoint" {
  description = "Default HTTP API endpoint (no custom domain)."
  value       = aws_apigatewayv2_api.http.api_endpoint
}

output "demo_distribution_domain_name" {
  description = "Default CloudFront domain of the guest demo."
  value       = aws_cloudfront_distribution.demo.domain_name
}

output "demo_distribution_arn" {
  description = "CloudFront distribution ARN, used by the demo bucket policy."
  value       = aws_cloudfront_distribution.demo.arn
}

output "cognito_user_pool_id" {
  description = "Owner user pool ID."
  value       = aws_cognito_user_pool.owner.id
}

output "cognito_client_id" {
  description = "Public app client ID (no secret)."
  value       = aws_cognito_user_pool_client.web.id
}

output "function_names" {
  description = "Lambda function name per class."
  value       = { for k, f in aws_lambda_function.this : k => f.function_name }
}
