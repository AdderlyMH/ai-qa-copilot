# HARD-003: operational alarms for the API function and the HTTP API. Each
# alarm notifies alarm_topic_arn (the alarm_notifications module) on ALARM and
# on OK when the topic is set; with the default "" it has no actions. Missing
# data (no traffic, so no datapoint) is not breaching. Dimensions come from
# this module's own resources, never from hard-coded names.

variable "alarm_topic_arn" {
  description = "SNS topic ARN for the alarms' alarm_actions and ok_actions (HARD-003). Empty: no actions."
  type        = string
  default     = ""
  nullable    = false
}

variable "api_errors_alarm_threshold" {
  description = "API function Lambda Errors (Sum over one 5-minute period) at or above which the alarm fires."
  type        = number
  default     = 1

  validation {
    condition     = var.api_errors_alarm_threshold >= 1 && floor(var.api_errors_alarm_threshold) == var.api_errors_alarm_threshold
    error_message = "api_errors_alarm_threshold must be a whole number of at least 1."
  }
}

variable "api_throttles_alarm_threshold" {
  description = "API function Lambda Throttles (Sum over one 5-minute period) at or above which the alarm fires."
  type        = number
  default     = 1

  validation {
    condition     = var.api_throttles_alarm_threshold >= 1 && floor(var.api_throttles_alarm_threshold) == var.api_throttles_alarm_threshold
    error_message = "api_throttles_alarm_threshold must be a whole number of at least 1."
  }
}

variable "http_api_4xx_alarm_threshold" {
  description = "HTTP API 4xx responses (Sum over one 5-minute period) at or above which the alarm fires; the throttling signal for an HTTP API."
  type        = number
  default     = 10

  validation {
    condition     = var.http_api_4xx_alarm_threshold >= 1 && floor(var.http_api_4xx_alarm_threshold) == var.http_api_4xx_alarm_threshold
    error_message = "http_api_4xx_alarm_threshold must be a whole number of at least 1."
  }
}

locals {
  alarm_actions = var.alarm_topic_arn == "" ? [] : [var.alarm_topic_arn]
}

# (a) Any API function error. Threshold 1 by default: a single-owner portfolio
# deployment has little traffic, so one unhandled error in five minutes is
# worth an email.
resource "aws_cloudwatch_metric_alarm" "api_errors" {
  alarm_name          = "${var.name_prefix}-api-lambda-errors"
  alarm_description   = "API function Lambda Errors >= ${var.api_errors_alarm_threshold} in 5 minutes (HARD-003)."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.this["api"].function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = var.api_errors_alarm_threshold
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

# (b) HTTP API throttling signal. HTTP APIs publish no throttle metric: the API
# Gateway Developer Guide, "Monitor CloudWatch metrics for HTTP APIs" (read
# 2026-11-12), lists only 4xx, 5xx, Count, IntegrationLatency, Latency and
# DataProcessed, with the ApiId dimension. A request rejected by the stage
# throttle (5 per second, burst 10) returns 429, which counts in 4xx, so 4xx is
# the closest signal. It also counts 401, 403, 404 and 413 responses. Threshold
# 10 by default: one throttled burst produces several 429s within seconds,
# while normal owner use (an occasional 401 after a token expires) stays well
# below 10 in five minutes.
resource "aws_cloudwatch_metric_alarm" "http_api_4xx" {
  alarm_name          = "${var.name_prefix}-http-api-4xx"
  alarm_description   = "HTTP API 4xx responses >= ${var.http_api_4xx_alarm_threshold} in 5 minutes; includes throttled 429s (HARD-003)."
  namespace           = "AWS/ApiGateway"
  metric_name         = "4xx"
  dimensions          = { ApiId = aws_apigatewayv2_api.http.id }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = var.http_api_4xx_alarm_threshold
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

# (c) Any Lambda throttle of the API function (account or function concurrency
# exhausted). Threshold 1 by default: no reserved concurrency is set (see the
# CKV_AWS_115 note on the functions), so any throttle means API requests were
# refused.
resource "aws_cloudwatch_metric_alarm" "api_throttles" {
  alarm_name          = "${var.name_prefix}-api-lambda-throttles"
  alarm_description   = "API function Lambda Throttles >= ${var.api_throttles_alarm_threshold} in 5 minutes (HARD-003)."
  namespace           = "AWS/Lambda"
  metric_name         = "Throttles"
  dimensions          = { FunctionName = aws_lambda_function.this["api"].function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = var.api_throttles_alarm_threshold
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}
