# Placeholders only. Copy to production.tfvars (ignored by Git) and fill in.
region                  = "us-east-1"
aws_account_id          = "000000000000"
github_plan_environment = "REPLACE_WITH_GITHUB_ENVIRONMENT"
state_bucket_name       = "REPLACE_WITH_STATE_BUCKET_NAME"

# Network (ADR-017). Example values. AZ names map to physical zones per
# account, so confirm the zones before applying.
vpc_cidr                  = "10.20.0.0/16"
compute_availability_zone = "us-east-1a"
egress_subnet_cidr        = "10.20.0.0/24"
parser_subnet_cidr        = "10.20.1.0/24"
public_subnet_cidr        = "10.20.2.0/24"

# Database (INFRA-003, ADR-020): two private subnets in two distinct zones.
# The Single-AZ instance is placed in compute_availability_zone, which must
# be one of database_availability_zones (a precondition checks this).
database_availability_zones = ["us-east-1a", "us-east-1b"]
database_subnet_cidrs       = ["10.20.10.0/24", "10.20.11.0/24"]
# Optional; defaults shown. engine_version must be 17.10 or later (17.5 to
# 17.11 offered in us-east-1 on 2026-10-16); it applies at creation only.
# database_engine_version          = "17.10"
# database_backup_retention_period = 7
# Required, no default (INFRA-008): FreeableMemory alarm threshold in MiB. ADR-020
# keeps it OPEN; the owner chooses it from the measured readings. No example
# number is given on purpose. Every plan of this root needs it.
# database_freeable_memory_alarm_threshold_mib = <owner-chosen MiB>

# Migration runner (INFRA-012). Off by default; the ECR repository exists either
# way. Turn on only to run migrations, with the pushed migrate image by digest,
# then turn off again (runbook in docs/INFRASTRUCTURE.md).
# migration_enabled   = true
# migration_image_uri = "<terraform output migration_ecr_repository_url>@sha256:<digest>"

# NAT instance (ADR-017). Change this value to replace the instance with the
# current AL2023 AMI; see the monthly runbook in docs/INFRASTRUCTURE.md.
nat_replacement_generation = "2026-10-13"

# Lambda images (INFRA-002 stage 4). FAKE example URIs: push real images to the
# ECR repositories first and use their digests.
image_uris = {
  api      = "000000000000.dkr.ecr.us-east-1.amazonaws.com/ai-qa-copilot-production-api@sha256:0000000000000000000000000000000000000000000000000000000000000000"
  parser   = "000000000000.dkr.ecr.us-east-1.amazonaws.com/ai-qa-copilot-production-parser@sha256:0000000000000000000000000000000000000000000000000000000000000000"
  general  = "000000000000.dkr.ecr.us-east-1.amazonaws.com/ai-qa-copilot-production-general@sha256:0000000000000000000000000000000000000000000000000000000000000000"
  executor = "000000000000.dkr.ecr.us-east-1.amazonaws.com/ai-qa-copilot-production-executor@sha256:0000000000000000000000000000000000000000000000000000000000000000"
}

# Cognito sub of the owner user (not a secret). Set after creating the user.
cognito_owner_subject = "REPLACE_WITH_OWNER_SUB"
model_provider        = "openai"
executor_enabled      = false
