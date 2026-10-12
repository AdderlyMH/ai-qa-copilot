# Production root. Stage 1 of INFRA-001 manages only the GitHub OIDC
# provider and the plan-only role. ADR-005 gates: no database resource until
# the provider is recorded; no compute resource until INFRA-002 records the
# compute service. Not applied.

terraform {
  required_version = ">= 1.16.5, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.68.0, < 7.0.0"
    }
  }

  # Partial configuration. Supply values with
  #   terraform init -backend-config=backend.hcl
  # using backend.example.hcl as the template. S3 native locking
  # (use_lockfile) is set there; DynamoDB locking is deprecated.
  backend "s3" {}
}

variable "region" {
  description = "AWS Region. No default: the Region is an open decision."
  type        = string
}

variable "aws_account_id" {
  description = "AWS account ID that this root may act on."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must be 12 digits."
  }
}

variable "project" {
  description = "Project slug."
  type        = string
  default     = "ai-qa-copilot"
}

variable "github_repository" {
  description = "GitHub repository allowed to assume the plan role."
  type        = string
  default     = "AdderlyMH/ai-qa-copilot"
}

variable "github_plan_environment" {
  description = "GitHub environment whose jobs may assume the plan role."
  type        = string
}

variable "state_bucket_name" {
  description = "State bucket created by infra/bootstrap; must match backend.hcl."
  type        = string
}

variable "state_key" {
  description = "State object key; must match backend.hcl."
  type        = string
  default     = "production/terraform.tfstate"
}

module "naming" {
  source      = "../../modules/naming"
  project     = var.project
  environment = "production"
}

provider "aws" {
  region              = var.region
  allowed_account_ids = [var.aws_account_id]

  default_tags {
    tags = module.naming.tags
  }
}

module "github_oidc_plan_role" {
  source             = "../../modules/github_oidc_plan_role"
  name_prefix        = module.naming.name_prefix
  github_repository  = var.github_repository
  github_environment = var.github_plan_environment
  state_bucket_name  = var.state_bucket_name
  state_key          = var.state_key
}

output "github_plan_role_arn" {
  description = "Role ARN for a future plan-only GitHub Actions job."
  value       = module.github_oidc_plan_role.plan_role_arn
}
