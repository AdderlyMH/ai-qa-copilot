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
  description = "Memory per function class in MB. Lambda allocates CPU in proportion to memory. The API is 1769 MB: at 512 MB its init phase hit the 10-second Lambda init limit (owner measurement 2026-10-20, CPU-bound). The other three are unmeasured."
  type        = map(number)
  default = {
    api      = 1769
    parser   = 512
    general  = 1024
    executor = 512
  }

  validation {
    condition     = toset(keys(var.memory_mb)) == toset(["api", "parser", "general", "executor"])
    error_message = "memory_mb must have exactly the keys api, parser, general and executor."
  }

  validation {
    condition     = alltrue([for mb in values(var.memory_mb) : mb >= 128 && mb <= 10240 && floor(mb) == mb])
    error_message = "Each memory_mb value must be a whole number of MB from 128 to 10240 (the Lambda range)."
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

variable "parser_database_url_enabled" {
  description = "Give the parser function its DATABASE_URL from the parser-database-url secret (ADR-018 fallback). False: the parser has no DATABASE_URL and fails closed. True: the secret must already hold a value, or the plan fails."
  type        = bool
  default     = false
  nullable    = false
}

variable "parser_database_url_secret_arn" {
  description = "ARN of the parser-database-url secret from the data plane."
  type        = string
}

variable "demo_cdn_enabled" {
  description = "Create the guest-demo CloudFront distribution and its origin access control. False: no CloudFront resource, the demo bucket policy has no CloudFront statement, and the guest page has no HTTPS host."
  type        = bool
  default     = true
  nullable    = false
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

# Owner app (INFRA-010 stage 2, ADR-022). No defaults: the values are the
# owner's addresses and live in the private production.tfvars.
variable "web_origins" {
  description = "Exact HTTPS origins of the owner web app allowed by the HTTP API CORS configuration (scheme and host, optional port; no path, no trailing slash, no wildcard)."
  type        = list(string)

  validation {
    condition = length(var.web_origins) > 0 && alltrue([
      for origin in var.web_origins :
      can(regex("^https://[a-z0-9]([a-z0-9-]*[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+(:[0-9]{1,5})?$", origin))
    ])
    error_message = "web_origins needs at least one entry; each must be https://<host>[:port] in lowercase, with no path, trailing slash or wildcard."
  }
}

variable "cognito_domain_prefix" {
  description = "Prefix of the Cognito prefix domain (<prefix>.auth.<region>.amazoncognito.com). A custom Cognito domain is not used (ADR-022)."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", var.cognito_domain_prefix))
    error_message = "cognito_domain_prefix must be 1 to 63 lowercase letters, digits or hyphens, and must not start or end with a hyphen."
  }
}

variable "cognito_callback_urls" {
  description = "Exact HTTPS callback URLs for the authorization code flow (no wildcard, no fragment)."
  type        = list(string)

  validation {
    condition = length(var.cognito_callback_urls) > 0 && alltrue([
      for url in var.cognito_callback_urls :
      can(regex("^https://[a-z0-9]([a-z0-9-]*[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+(:[0-9]{1,5})?(/[^*#\\s]*)?$", url))
    ])
    error_message = "cognito_callback_urls needs at least one entry; each must be an exact https:// URL with no wildcard or fragment."
  }
}

variable "cognito_logout_urls" {
  description = "Exact HTTPS sign-out URLs (no wildcard, no fragment)."
  type        = list(string)

  validation {
    condition = length(var.cognito_logout_urls) > 0 && alltrue([
      for url in var.cognito_logout_urls :
      can(regex("^https://[a-z0-9]([a-z0-9-]*[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+(:[0-9]{1,5})?(/[^*#\\s]*)?$", url))
    ])
    error_message = "cognito_logout_urls needs at least one entry; each must be an exact https:// URL with no wildcard or fragment."
  }
}

data "aws_partition" "current" {}
data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

# ADR-018 fallback (INFRA-008 Stage B), accepted exposure for the parser only:
# Terraform reads the parser's database URL at plan time, so the value is
# stored in Terraform state (S3 state bucket, SSE-S3, versioned) and in the
# Lambda function configuration. The provider marks secret_string sensitive,
# so plans redact it; state does not. Rotation: run the migration runner's
# create_parser_user with rotate=true, then re-apply this module.
data "aws_secretsmanager_secret_version" "parser_database_url" {
  count     = var.parser_database_url_enabled ? 1 : 0
  secret_id = var.parser_database_url_secret_arn
}

locals {
  parser_database_url_environment = var.parser_database_url_enabled ? {
    DATABASE_URL = sensitive(data.aws_secretsmanager_secret_version.parser_database_url[0].secret_string)
  } : {}
}

locals {
  region     = data.aws_region.current.region
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition

  function_names = { for k in ["api", "parser", "general", "executor"] : k => "${var.name_prefix}-${k}" }

  cognito_issuer = "https://cognito-idp.${local.region}.amazonaws.com/${aws_cognito_user_pool.owner.id}"

  # Non-secret settings only. The API and general worker get the two secret
  # ARNs; the values are read at cold start (secrets_bootstrap.py) and never
  # appear here. MODEL_PROVIDER stays unset on the API (OpenAI default) and
  # openai on the general worker. The API sends one parser wake-up per
  # accepted upload (parser_wakeup.py, PARSER_QUEUE_URL); the general wake-up
  # flag stays unset until INFRA-013 gives the general worker an embedding
  # adapter.
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
      LOCAL_AUTH_BYPASS_ENABLED = "false"

      AI_QA_COPILOT_PARSER_WAKEUP_ENABLED = "true"
    })
    # The parser is the only function whose environment holds a database URL
    # (ADR-018 fallback, INFRA-008 Stage B): it cannot reach Secrets Manager.
    parser = merge({
      APP_ENV               = "production"
      PARSER_WORKER_ROLE    = "restricted-parser"
      PARSER_WORKER_NETWORK = "none"
      DATA_BUCKET_NAME      = var.data_bucket_name
    }, local.parser_database_url_environment)
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
  #checkov:skip=CKV_AWS_173:The api, general and executor environments hold only non-secret settings (secret ARNs, never values). The parser environment holds one credential, its restricted DATABASE_URL, only while parser_database_url_enabled is true, by the accepted ADR-018 fallback (the parser has no route to Secrets Manager; the value is also in Terraform state). Lambda's default encryption; no customer managed KMS key.
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

  # Owner web app on its own origin (ADR-022). API Gateway answers preflight
  # requests and ignores CORS headers from the integration; FastAPI sets none.
  # Methods are those the API routes serve to the web app; /demo accepts more
  # methods only to deny them. Bearer header, no cookies: no credentials.
  cors_configuration {
    allow_origins     = var.web_origins
    allow_methods     = ["DELETE", "GET", "POST"]
    allow_headers     = ["authorization", "content-type", "x-upload-filename"]
    expose_headers    = ["x-correlation-id"]
    allow_credentials = false
    max_age           = 600
  }
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

# Everything below exists only while demo_cdn_enabled is true. The origin
# access control serves only this distribution, so it is gated with it.
locals {
  demo_cdn_count = var.demo_cdn_enabled ? 1 : 0
}

data "aws_cloudfront_cache_policy" "optimized" {
  count = local.demo_cdn_count
  name  = "Managed-CachingOptimized"
}

data "aws_cloudfront_response_headers_policy" "security" {
  count = local.demo_cdn_count
  name  = "Managed-SecurityHeadersPolicy"
}

# Addresses before the flag existed; nothing was applied under them, so these
# are no-ops today and keep a future plan from replacing an applied resource.
moved {
  from = aws_cloudfront_origin_access_control.demo
  to   = aws_cloudfront_origin_access_control.demo[0]
}

moved {
  from = aws_cloudfront_distribution.demo
  to   = aws_cloudfront_distribution.demo[0]
}

resource "aws_cloudfront_origin_access_control" "demo" {
  count                             = local.demo_cdn_count
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
  count               = local.demo_cdn_count
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
    origin_access_control_id = aws_cloudfront_origin_access_control.demo[0].id
  }

  default_cache_behavior {
    target_origin_id           = "demo-publications"
    viewer_protocol_policy     = "https-only"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = data.aws_cloudfront_cache_policy.optimized[0].id
    response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security[0].id
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
  # The deployed pool is on ESSENTIALS (owner read, 2026-10-23); pinned so a
  # plan shows no tier change. Managed login needs a tier other than LITE.
  user_pool_tier = "ESSENTIALS"

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

# Prefix domain for managed login (ADR-022): no custom domain, so no
# CloudFront distribution and no ACM certificate. Version 2 is managed login,
# which needs a non-LITE tier and a branding style per app client.
resource "aws_cognito_user_pool_domain" "owner" {
  domain                = var.cognito_domain_prefix
  user_pool_id          = aws_cognito_user_pool.owner.id
  managed_login_version = 2
}

# Public client: no client secret. Authorization code only; a public client
# must send PKCE from the web app (stage 4). SRP and refresh-token flows are
# kept for the existing owner API check.
resource "aws_cognito_user_pool_client" "web" {
  name                                 = "${var.name_prefix}-web"
  user_pool_id                         = aws_cognito_user_pool.owner.id
  generate_secret                      = false
  explicit_auth_flows                  = ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid"]
  callback_urls                        = var.cognito_callback_urls
  logout_urls                          = var.cognito_logout_urls
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

# A client created through the API has no branding style, and managed login
# is not available to it until one exists (Cognito CreateUserPoolDomain and
# managed login documentation). Cognito's default style, no custom assets.
resource "aws_cognito_managed_login_branding" "web" {
  user_pool_id                = aws_cognito_user_pool.owner.id
  client_id                   = aws_cognito_user_pool_client.web.id
  use_cognito_provided_values = true
}

# ---------------------------------------------------------------- Outputs

output "http_api_endpoint" {
  description = "Default HTTP API endpoint (no custom domain)."
  value       = aws_apigatewayv2_api.http.api_endpoint
}

output "demo_distribution_domain_name" {
  description = "Default CloudFront domain of the guest demo, or null while demo_cdn_enabled is false."
  value       = var.demo_cdn_enabled ? aws_cloudfront_distribution.demo[0].domain_name : null
}

output "demo_distribution_arn" {
  description = "CloudFront distribution ARN for the demo bucket policy, or null while demo_cdn_enabled is false."
  value       = var.demo_cdn_enabled ? aws_cloudfront_distribution.demo[0].arn : null
}

output "cognito_user_pool_id" {
  description = "Owner user pool ID."
  value       = aws_cognito_user_pool.owner.id
}

output "cognito_client_id" {
  description = "Public app client ID (no secret)."
  value       = aws_cognito_user_pool_client.web.id
}

output "cognito_domain_base_url" {
  description = "Base address of the Cognito prefix domain for the managed login and OAuth endpoints (not a secret)."
  value       = "https://${aws_cognito_user_pool_domain.owner.domain}.auth.${data.aws_region.current.region}.amazoncognito.com"
}

output "function_names" {
  description = "Lambda function name per class."
  value       = { for k, f in aws_lambda_function.this : k => f.function_name }
}
