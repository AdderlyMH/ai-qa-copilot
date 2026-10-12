terraform {
  required_version = ">= 1.16.5, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.68.0, < 7.0.0"
    }
  }
}

# GitHub Actions OIDC trust and a plan-only role.
# Trust conditions follow AWS IAM and GitHub documentation read 2026-10-12;
# see docs/INFRASTRUCTURE.md. The role can read Terraform state, manage only
# the state lock file, and read the resources this stage manages. It has no
# write permission on any managed resource.

variable "name_prefix" {
  description = "Resource name prefix from the naming module."
  type        = string
}

variable "github_repository" {
  description = "GitHub repository in OWNER/REPO form."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$", var.github_repository))
    error_message = "github_repository must be OWNER/REPO without wildcards."
  }
}

variable "github_environment" {
  description = "GitHub environment whose jobs may assume the plan role."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9._-]+$", var.github_environment))
    error_message = "github_environment must be a literal name without wildcards."
  }
}

variable "state_bucket_name" {
  description = "Name of the S3 bucket holding Terraform state."
  type        = string
}

variable "state_key" {
  description = "Object key of this root module's state file."
  type        = string
}

locals {
  oidc_host = "token.actions.githubusercontent.com"
  role_name = "${var.name_prefix}-github-plan"
}

data "aws_partition" "current" {}
data "aws_caller_identity" "current" {}

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://${local.oidc_host}"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "trust" {
  statement {
    sid     = "GitHubEnvironmentPlanOnly"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Exact subject: one repository and one GitHub environment, no wildcard.
    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:sub"
      values   = ["repo:${var.github_repository}:environment:${var.github_environment}"]
    }
  }
}

resource "aws_iam_role" "plan" {
  name                 = local.role_name
  description          = "Terraform plan only for ${var.github_repository} (${var.github_environment})."
  assume_role_policy   = data.aws_iam_policy_document.trust.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "plan" {
  statement {
    sid       = "ListStateBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::${var.state_bucket_name}"]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = [var.state_key, "${var.state_key}.tflock"]
    }
  }

  statement {
    sid       = "ReadState"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::${var.state_bucket_name}/${var.state_key}"]
  }

  # S3 native locking needs GetObject, PutObject and DeleteObject on the
  # lock file only (Terraform S3 backend documentation, read 2026-10-12).
  statement {
    sid       = "ManageStateLockFile"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::${var.state_bucket_name}/${var.state_key}.tflock"]
  }

  # Read-only refresh of the resources this stage manages. Later stages add
  # read actions for the resources they introduce, never write actions.
  statement {
    sid    = "ReadManagedIdentityResources"
    effect = "Allow"
    actions = [
      "iam:GetOpenIDConnectProvider",
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:ListAttachedRolePolicies",
      "iam:ListRolePolicies",
    ]
    resources = [
      aws_iam_openid_connect_provider.github.arn,
      "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:role/${local.role_name}",
    ]
  }
}

resource "aws_iam_role_policy" "plan" {
  name   = "terraform-plan-read-only"
  role   = aws_iam_role.plan.id
  policy = data.aws_iam_policy_document.plan.json
}

output "oidc_provider_arn" {
  description = "ARN of the GitHub Actions OIDC provider."
  value       = aws_iam_openid_connect_provider.github.arn
}

output "plan_role_arn" {
  description = "ARN of the plan-only role for GitHub Actions."
  value       = aws_iam_role.plan.arn
}
