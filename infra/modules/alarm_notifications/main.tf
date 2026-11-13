terraform {
  required_version = ">= 1.16.5, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.68.0, < 7.0.0"
    }
  }
}

# HARD-003: the notification path for CloudWatch alarms. One SNS topic,
# encrypted with a customer managed KMS key, that only CloudWatch in this
# account may publish to, and one email subscription.
#
# Why a customer managed key: the AWS managed key alias/aws/sns has a fixed key
# policy that does not let cloudwatch.amazonaws.com use it, so alarm publishes
# to a topic encrypted with it fail. The Amazon SNS Developer Guide, "Managing
# Amazon SNS encryption keys and costs", section "Enable compatibility between
# event sources from AWS services and encrypted topics" (read 2026-11-12), says
# to use a customer managed key and to grant the service principal (CloudWatch:
# cloudwatch.amazonaws.com) kms:GenerateDataKey* and kms:Decrypt in the key
# policy. It does not ask for an sns.amazonaws.com grant, so none is given.
# Whether a real alarm reaches the inbox is NOT verified until the owner's test
# alarm email arrives (docs/INFRASTRUCTURE.md, "HARD-003 alarms, 2026-11-12").

variable "name_prefix" {
  description = "Resource name prefix from the naming module."
  type        = string
}

variable "alarm_email" {
  description = "Email address subscribed to the alarm topic. Private: set only in production.tfvars. The subscription stays Pending until the confirmation email is clicked."
  type        = string
  sensitive   = true

  validation {
    condition     = length(trimspace(var.alarm_email)) > 0 && strcontains(var.alarm_email, "@")
    error_message = "alarm_email must be a non-empty email address."
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  name       = "${var.name_prefix}-alarms"
  account_id = data.aws_caller_identity.current.account_id
}

# Key policy. The account root administers the key, which delegates key
# management to IAM policies in this account (the KMS default key policy). The
# only service grant is CloudWatch, limited to this account by
# aws:SourceAccount, with the two actions the SNS guide lists. aws:SourceArn is
# not added: the guide leaves its exact value to each service's documentation,
# which was not checked here.
#
# The policy is written inline rather than as an aws_iam_policy_document: in a
# key policy "Resource": "*" means this key only, and the generic IAM-document
# checks (CKV_AWS_109, CKV_AWS_111, CKV_AWS_356) read it as every resource.
# The statements are the same either way.
resource "aws_kms_key" "alarms" {
  description             = "Encrypts the HARD-003 alarm SNS topic; CloudWatch alarms in this account may use it."
  key_usage               = "ENCRYPT_DECRYPT"
  enable_key_rotation     = true
  deletion_window_in_days = 7

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AccountRootAdministers"
        Effect    = "Allow"
        Principal = { AWS = "arn:${data.aws_partition.current.partition}:iam::${local.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "CloudWatchAlarmsUseKey"
        Effect    = "Allow"
        Principal = { Service = "cloudwatch.amazonaws.com" }
        Action    = ["kms:GenerateDataKey*", "kms:Decrypt"]
        Resource  = "*"
        Condition = { StringEquals = { "aws:SourceAccount" = local.account_id } }
      },
    ]
  })

  tags = {
    Name = local.name
  }
}

resource "aws_kms_alias" "alarms" {
  name          = "alias/${local.name}"
  target_key_id = aws_kms_key.alarms.key_id
}

resource "aws_sns_topic" "alarms" {
  name              = local.name
  kms_master_key_id = aws_kms_key.alarms.arn

  tags = {
    Name = local.name
  }
}

# Replaces the default topic policy: only CloudWatch, on behalf of this
# account, may publish. Principals in this account keep the access their IAM
# policies give them.
data "aws_iam_policy_document" "topic" {
  statement {
    sid       = "CloudWatchAlarmsPublish"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alarms.arn]

    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_sns_topic_policy" "alarms" {
  arn    = aws_sns_topic.alarms.arn
  policy = data.aws_iam_policy_document.topic.json
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

output "topic_arn" {
  description = "ARN of the alarm SNS topic, for alarm_actions and ok_actions."
  value       = aws_sns_topic.alarms.arn
}
