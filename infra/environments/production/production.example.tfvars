# Placeholders only. Copy to production.tfvars (ignored by Git) and fill in.
region                  = "us-east-1"
aws_account_id          = "000000000000"
github_plan_environment = "REPLACE_WITH_GITHUB_ENVIRONMENT"
state_bucket_name       = "REPLACE_WITH_STATE_BUCKET_NAME"

# Network (ADR-017). Example values; 10.20.10.0/24 and 10.20.11.0/24 are kept
# free for the INFRA-003 database subnets. AZ names map to physical zones per
# account, so confirm the zone before applying.
vpc_cidr                  = "10.20.0.0/16"
compute_availability_zone = "us-east-1a"
egress_subnet_cidr        = "10.20.0.0/24"
parser_subnet_cidr        = "10.20.1.0/24"
public_subnet_cidr        = "10.20.2.0/24"

# NAT instance (ADR-017). Change this value to replace the instance with the
# current AL2023 AMI; see the monthly runbook in docs/INFRASTRUCTURE.md.
nat_replacement_generation = "2026-10-13"
