# Production root: the GitHub OIDC provider and plan-only role (INFRA-001), the
# VPC network layout (INFRA-002 stage 1), the NAT instance (stage 2), the data
# plane (stage 3) and compute, API, guest-demo CDN and Cognito (stage 4), per
# ADR-017. ADR-005 database gate:
# no database resource, subnet group or database connectivity resource until
# the provider is recorded (INFRA-003). Not applied.

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

variable "vpc_cidr" {
  description = "IPv4 CIDR of the production VPC (example 10.20.0.0/16)."
  type        = string
}

variable "compute_availability_zone" {
  description = "Availability Zone name for the compute subnets (example us-east-1a)."
  type        = string
}

variable "egress_subnet_cidr" {
  description = "IPv4 CIDR of the egress-compute subnet (example 10.20.0.0/24)."
  type        = string
}

variable "parser_subnet_cidr" {
  description = "IPv4 CIDR of the parser subnet (example 10.20.1.0/24)."
  type        = string
}

variable "public_subnet_cidr" {
  description = "IPv4 CIDR of the public subnet for the NAT instance (example 10.20.2.0/24)."
  type        = string
}

variable "image_uris" {
  description = "Container image URI per Lambda function class (api, parser, general, executor); images must exist in ECR before apply."
  type        = map(string)
}

variable "cognito_owner_subject" {
  description = "Cognito sub of the single owner user (not a secret); see the runbook in docs/INFRASTRUCTURE.md."
  type        = string
}

variable "model_provider" {
  description = "Model provider for the general worker (openai or anthropic)."
  type        = string
  default     = "openai"
}

variable "executor_enabled" {
  description = "Enable the executor trigger; keep false until SG-08 executor egress control exists (INFRA-004)."
  type        = bool
  default     = false
}

variable "nat_replacement_generation" {
  description = "Change to replace the NAT instance with the current AL2023 AMI (monthly runbook in docs/INFRASTRUCTURE.md)."
  type        = string
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

module "network" {
  source                    = "../../modules/network"
  name_prefix               = module.naming.name_prefix
  vpc_cidr                  = var.vpc_cidr
  compute_availability_zone = var.compute_availability_zone
  egress_subnet_cidr        = var.egress_subnet_cidr
  parser_subnet_cidr        = var.parser_subnet_cidr
  public_subnet_cidr        = var.public_subnet_cidr
}

module "nat_instance" {
  source                           = "../../modules/nat_instance"
  name_prefix                      = module.naming.name_prefix
  vpc_id                           = module.network.vpc_id
  public_subnet_id                 = module.network.public_subnet_id
  egress_route_table_id            = module.network.egress_route_table_id
  egress_subnet_cidr               = module.network.egress_subnet_cidr
  egress_compute_security_group_id = module.network.egress_compute_security_group_id
  replacement_generation           = var.nat_replacement_generation
}

module "data_plane" {
  source                           = "../../modules/data_plane"
  name_prefix                      = module.naming.name_prefix
  demo_cloudfront_distribution_arn = module.compute_api.demo_distribution_arn
}

module "compute_api" {
  source                           = "../../modules/compute_api"
  name_prefix                      = module.naming.name_prefix
  image_uris                       = var.image_uris
  egress_subnet_id                 = module.network.egress_subnet_id
  parser_subnet_id                 = module.network.parser_subnet_id
  egress_compute_security_group_id = module.network.egress_compute_security_group_id
  parser_security_group_id         = module.network.parser_security_group_id
  role_arns                        = module.data_plane.function_role_arns
  log_group_names                  = module.data_plane.log_group_names
  queue_arns                       = module.data_plane.queue_arns
  queue_urls                       = module.data_plane.queue_urls
  ecr_repositories                 = module.data_plane.ecr_repositories
  data_bucket_name                 = module.data_plane.data_bucket_name
  demo_bucket_name                 = module.data_plane.demo_bucket_name
  demo_bucket_regional_domain_name = module.data_plane.demo_bucket_regional_domain_name
  cognito_owner_subject            = var.cognito_owner_subject
  model_provider                   = var.model_provider
  executor_enabled                 = var.executor_enabled
}

output "http_api_endpoint" {
  description = "Default HTTP API endpoint."
  value       = module.compute_api.http_api_endpoint
}

output "demo_distribution_domain_name" {
  description = "Default CloudFront domain of the guest demo."
  value       = module.compute_api.demo_distribution_domain_name
}

output "cognito_user_pool_id" {
  description = "Owner user pool ID."
  value       = module.compute_api.cognito_user_pool_id
}

output "data_plane_ecr_repository_urls" {
  description = "ECR repository URL per Lambda function class."
  value       = module.data_plane.ecr_repository_urls
}

output "nat_public_ip" {
  description = "Elastic IP used for all egress through the NAT instance."
  value       = module.nat_instance.nat_public_ip
}

output "vpc_id" {
  description = "Production VPC ID."
  value       = module.network.vpc_id
}

output "github_plan_role_arn" {
  description = "Role ARN for a future plan-only GitHub Actions job."
  value       = module.github_oidc_plan_role.plan_role_arn
}
