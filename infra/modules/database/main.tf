terraform {
  required_version = ">= 1.16.5, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.68.0, < 7.0.0"
    }
  }
}

# INFRA-003: the production PostgreSQL instance decided in ADR-020.
# RDS for PostgreSQL 17 (minor 17.10 or later), db.t4g.micro, Single-AZ in a
# DB subnet group spanning two Availability Zones, gp3 20 GiB, encrypted with
# the RDS AWS managed key, not publicly accessible. The master password is
# generated and kept by RDS in Secrets Manager (manage_master_user_password),
# so no password is an input, a variable or part of Terraform state.
#
# Deliberately absent (cost, ADR-020): Performance Insights, Enhanced
# Monitoring, RDS Proxy, read replicas and storage autoscaling. Not created
# here: database users, grants, extensions or any SQL (INFRA-012), the
# FreeableMemory alarm and parameter tuning (INFRA-008, threshold OPEN), and
# wiring the endpoint into the Lambda functions (INFRA-008). Not applied.

variable "name_prefix" {
  description = "Resource name prefix from the naming module."
  type        = string
}

variable "subnet_ids" {
  description = "The two database subnet IDs (two Availability Zones) from the network module."
  type        = list(string)

  validation {
    condition     = length(var.subnet_ids) == 2
    error_message = "subnet_ids must contain exactly the two database subnets."
  }
}

variable "security_group_id" {
  description = "Database security group ID from the network module."
  type        = string
}

variable "subnet_availability_zones" {
  description = "Availability Zones of the two database subnets, from the network module."
  type        = list(string)
}

variable "availability_zone" {
  description = "Availability Zone for the Single-AZ instance; the production root passes compute_availability_zone so the database sits next to the Lambda subnets. Must be one of the database subnet zones."
  type        = string
}

variable "engine_version" {
  description = "PostgreSQL 17 minor version at creation, 17.10 or later (ADR-020: first 17.x with pgvector 0.8.2). The owner confirmed 17.5 to 17.11 offered in us-east-1 on 2026-10-16."
  type        = string
  default     = "17.10"

  validation {
    condition     = can(regex("^17\\.[0-9]+$", var.engine_version)) && try(tonumber(split(".", var.engine_version)[1]) >= 10, false)
    error_message = "engine_version must be PostgreSQL 17 at minor 17.10 or later, for example 17.10."
  }
}

variable "parameter_group_family" {
  description = "DB parameter group family for PostgreSQL 17 (postgres17, confirmed by the owner's describe-db-engine-versions output on 2026-10-16)."
  type        = string
  default     = "postgres17"

  validation {
    condition     = var.parameter_group_family == "postgres17"
    error_message = "parameter_group_family must be postgres17 for PostgreSQL 17."
  }
}

variable "backup_retention_period" {
  description = "Automated backup retention in days (1 to 35). Backup storage is free up to the total provisioned database storage in the Region (RDS FAQ, ADR-020)."
  type        = number
  default     = 7

  validation {
    condition     = var.backup_retention_period >= 1 && var.backup_retention_period <= 35 && floor(var.backup_retention_period) == var.backup_retention_period
    error_message = "backup_retention_period must be a whole number of days from 1 to 35; 0 would disable automated backups."
  }
}

locals {
  identifier = "${var.name_prefix}-postgres"
}

resource "aws_db_subnet_group" "this" {
  name        = "${var.name_prefix}-database"
  description = "Two private database subnets in two Availability Zones (ADR-020)"
  subnet_ids  = var.subnet_ids

  tags = {
    Name = "${var.name_prefix}-database"
  }
}

# Dedicated group that keeps the family defaults. The only parameter set is
# rds.force_ssl = 1, which is already the RDS default for PostgreSQL 15 and
# later; it is pinned so TLS enforcement is explicit and does not depend on a
# default (Checkov CKV2_AWS_69). No tuning here: shared_buffers and any other
# parameter are INFRA-008 scope.
resource "aws_db_parameter_group" "this" {
  name        = "${var.name_prefix}-postgres17"
  family      = var.parameter_group_family
  description = "PostgreSQL 17 defaults with TLS required; no tuning (INFRA-008)"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  tags = {
    Name = "${var.name_prefix}-postgres17"
  }
}

resource "aws_db_instance" "this" {
  #checkov:skip=CKV_AWS_157:Single-AZ by owner decision for cost (ADR-020); the DB subnet group spans two zones so the instance can be recreated in the other one; no RPO or RTO is claimed.
  #checkov:skip=CKV_AWS_118:Enhanced Monitoring is off for cost (ADR-020); basic CloudWatch metrics such as FreeableMemory and CPUSurplusCreditsCharged remain available.
  #checkov:skip=CKV_AWS_353:Performance Insights is off for cost (ADR-020).
  #checkov:skip=CKV_AWS_129:No log export to CloudWatch Logs for cost: RDS would create a log group without retention; PostgreSQL logs stay downloadable from RDS. Revisit in HARD-001.
  identifier     = local.identifier
  engine         = "postgres"
  engine_version = var.engine_version
  instance_class = "db.t4g.micro"

  # gp3 below 400 GiB has a fixed 3,000 IOPS and 125 MiB/s baseline, so iops
  # and storage_throughput are not set. max_allocated_storage is unset: no
  # storage autoscaling.
  storage_type      = "gp3"
  allocated_storage = 20
  storage_encrypted = true

  db_name                     = "ai_qa_copilot"
  username                    = "copilot_master"
  manage_master_user_password = true
  port                        = 5432

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [var.security_group_id]
  parameter_group_name   = aws_db_parameter_group.this.name
  publicly_accessible    = false
  multi_az               = false
  availability_zone      = var.availability_zone
  network_type           = "IPV4"

  iam_database_authentication_enabled = true

  backup_retention_period    = var.backup_retention_period
  copy_tags_to_snapshot      = true
  deletion_protection        = true
  skip_final_snapshot        = false
  final_snapshot_identifier  = "${local.identifier}-final"
  auto_minor_version_upgrade = true
  apply_immediately          = false

  performance_insights_enabled = false
  monitoring_interval          = 0

  tags = {
    Name = local.identifier
  }

  lifecycle {
    precondition {
      condition     = contains(var.subnet_availability_zones, var.availability_zone)
      error_message = "availability_zone must be one of the two database subnet Availability Zones."
    }

    # With auto_minor_version_upgrade, RDS raises the minor version itself.
    # Provider 6.68.0 then reads the running version into engine_version
    # (compareActualEngineVersion keeps "17.10" only for a "17.10." prefix) and
    # aws_db_instance has no diff suppression, so the next plan would try to
    # downgrade 17.11 -> 17.10, which RDS rejects. engine_version is used at
    # creation only; the running version is engine_version_actual. Remove this
    # entry deliberately for a planned version change.
    ignore_changes = [engine_version]
  }
}

# Surplus CPU credits are the only usage-based charge of the instance (RDS
# db.t4g runs in Unlimited mode). No alarm action or SNS topic: there is no
# confirmed subscriber, so the alarm is visible in the CloudWatch console only.
resource "aws_cloudwatch_metric_alarm" "cpu_surplus_credits_charged" {
  alarm_name          = "${local.identifier}-cpu-surplus-credits-charged"
  alarm_description   = "Charged surplus CPU credits on the db.t4g.micro instance (ADR-020). Console only; no notification."
  namespace           = "AWS/RDS"
  metric_name         = "CPUSurplusCreditsCharged"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.this.identifier }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
}

output "instance_identifier" {
  description = "RDS DB instance identifier."
  value       = aws_db_instance.this.identifier
}

output "endpoint_address" {
  description = "DNS address of the instance (no credentials)."
  value       = aws_db_instance.this.address
}

output "port" {
  description = "PostgreSQL port."
  value       = aws_db_instance.this.port
}

output "resource_id" {
  description = "DbiResourceId, needed for the rds-db:connect ARN (ADR-020)."
  value       = aws_db_instance.this.resource_id
}

output "master_user_secret_arn" {
  description = "ARN of the RDS-managed master user secret in Secrets Manager (the ARN only, never the value)."
  value       = aws_db_instance.this.master_user_secret[0].secret_arn
}

output "security_group_id" {
  description = "Database security group ID."
  value       = var.security_group_id
}
