terraform {
  required_version = ">= 1.16.5, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.68.0, < 7.0.0"
    }
  }
}

# INFRA-002 stages 1 and 2: VPC layout from ADR-017. Stage 1 created only
# free resources. Stage 2 adds the public subnet, internet gateway and public
# route table used by the NAT instance (infra/modules/nat_instance); the NAT
# instance, its Elastic IP and the egress default route live in that module.
# No interface endpoint, NAT gateway or database resource exists here.
# Database subnets and the database security group are deferred to INFRA-003
# (ADR-005 database gate). Network ACLs stay at the VPC default (allow all);
# isolation is enforced by route tables and security groups, which are
# stateful and per-resource. The parser's no-internet guarantee comes from its
# route table, which has no route beyond the local VPC route and the S3
# gateway endpoint.

variable "name_prefix" {
  description = "Resource name prefix from the naming module."
  type        = string
}

variable "vpc_cidr" {
  description = "IPv4 CIDR of the VPC, for example 10.20.0.0/16."
  type        = string

  validation {
    condition     = can(cidrhost(var.vpc_cidr, 0))
    error_message = "vpc_cidr must be a valid IPv4 CIDR block."
  }
}

variable "compute_availability_zone" {
  description = "Availability Zone name for the compute subnets, for example us-east-1a. AZ names map to physical zones per account."
  type        = string
}

variable "egress_subnet_cidr" {
  description = "IPv4 CIDR of the egress-compute subnet (API, general worker, executor), for example 10.20.0.0/24."
  type        = string

  validation {
    condition     = can(cidrhost(var.egress_subnet_cidr, 0))
    error_message = "egress_subnet_cidr must be a valid IPv4 CIDR block."
  }
}

variable "public_subnet_cidr" {
  description = "IPv4 CIDR of the public subnet that holds only the NAT instance, for example 10.20.2.0/24."
  type        = string

  validation {
    condition     = can(cidrhost(var.public_subnet_cidr, 0))
    error_message = "public_subnet_cidr must be a valid IPv4 CIDR block."
  }
}

variable "parser_subnet_cidr" {
  description = "IPv4 CIDR of the parser subnet, for example 10.20.1.0/24. It never has an internet or NAT route."
  type        = string

  validation {
    condition     = can(cidrhost(var.parser_subnet_cidr, 0))
    error_message = "parser_subnet_cidr must be a valid IPv4 CIDR block."
  }
}

data "aws_region" "current" {}

resource "aws_vpc" "main" {
  #checkov:skip=CKV2_AWS_11:VPC flow logs are off in this stage to avoid log ingestion and storage cost; tracked as an open item for HARD-001.
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "${var.name_prefix}-vpc"
  }
}

# Removes every rule from the VPC default security group so nothing can use it.
resource "aws_default_security_group" "default" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${var.name_prefix}-default-locked"
  }
}

resource "aws_subnet" "egress" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.egress_subnet_cidr
  availability_zone       = var.compute_availability_zone
  map_public_ip_on_launch = false

  tags = {
    Name = "${var.name_prefix}-egress-compute"
    Tier = "egress-compute"
  }
}

# Public subnet for the NAT instance only. No automatic public IPs: the NAT
# instance gets its address from an Elastic IP.
resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnet_cidr
  availability_zone       = var.compute_availability_zone
  map_public_ip_on_launch = false

  tags = {
    Name = "${var.name_prefix}-public-nat"
    Tier = "public"
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${var.name_prefix}-igw"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${var.name_prefix}-public-nat"
  }
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.main.id
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

resource "aws_subnet" "parser" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.parser_subnet_cidr
  availability_zone       = var.compute_availability_zone
  map_public_ip_on_launch = false

  tags = {
    Name = "${var.name_prefix}-parser"
    Tier = "parser"
  }
}

# Egress route table: local route, S3 gateway endpoint route, and the default
# route to the NAT instance network interface (aws_route in
# infra/modules/nat_instance, INFRA-002 stage 2).
resource "aws_route_table" "egress" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${var.name_prefix}-egress-compute"
  }
}

# Parser route table. `route = []` makes Terraform remove any route it finds
# that is not in this configuration, and the postcondition fails the plan or
# apply if a route ever appears. Gateway endpoint routes are managed by the
# endpoint, not listed here.
resource "aws_route_table" "parser" {
  vpc_id = aws_vpc.main.id
  route  = []

  tags = {
    Name = "${var.name_prefix}-parser"
  }

  lifecycle {
    postcondition {
      condition     = length(self.route) == 0
      error_message = "The parser route table must not contain any route to the internet, a NAT device or another network."
    }
  }
}

resource "aws_route_table_association" "egress" {
  subnet_id      = aws_subnet.egress.id
  route_table_id = aws_route_table.egress.id
}

resource "aws_route_table_association" "parser" {
  subnet_id      = aws_subnet.parser.id
  route_table_id = aws_route_table.parser.id
}

# Gateway endpoints have no additional charge.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${data.aws_region.current.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.egress.id, aws_route_table.parser.id]

  tags = {
    Name = "${var.name_prefix}-s3-gateway"
  }
}

# Parser: no ingress. Terraform removes the AWS default allow-all egress rule;
# the only egress rule is HTTPS to the S3 prefix list of the gateway endpoint
# (INFRA-002 stage 3), which the parser subnet reaches without any internet
# route. A database rule is added only when the database exists (INFRA-003).
resource "aws_security_group" "parser" {
  #checkov:skip=CKV2_AWS_5:Attached to the parser Lambda in a later INFRA-002 stage; no compute exists yet.
  name        = "${var.name_prefix}-parser"
  description = "Restricted parser worker: no ingress, egress only to S3 through the gateway endpoint"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${var.name_prefix}-parser"
  }
}

resource "aws_vpc_security_group_egress_rule" "parser_s3_gateway" {
  security_group_id = aws_security_group.parser.id
  description       = "HTTPS to Amazon S3 through the gateway endpoint"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  prefix_list_id    = aws_vpc_endpoint.s3.prefix_list_id
}

# Egress compute: API, general worker and executor. Outbound HTTPS only.
# SG-08 is NOT met: this allows any HTTPS destination. INFRA-004 owns the
# executor egress control (ADR-017 open item).
resource "aws_security_group" "egress_compute" {
  #checkov:skip=CKV2_AWS_5:Attached to the API, worker and executor Lambdas in a later INFRA-002 stage; no compute exists yet.
  name        = "${var.name_prefix}-egress-compute"
  description = "API, general worker and executor: outbound HTTPS only"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${var.name_prefix}-egress-compute"
  }
}

# Outbound HTTPS to any address is needed for the Cognito JWKS endpoint and the
# model provider through the NAT instance (stage 2).
resource "aws_vpc_security_group_egress_rule" "egress_compute_https" {
  security_group_id = aws_security_group.egress_compute.id
  description       = "Outbound HTTPS"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

output "vpc_id" {
  description = "VPC ID."
  value       = aws_vpc.main.id
}

output "egress_subnet_id" {
  description = "Egress-compute subnet ID."
  value       = aws_subnet.egress.id
}

output "public_subnet_id" {
  description = "Public subnet ID for the NAT instance."
  value       = aws_subnet.public.id
}

output "parser_subnet_id" {
  description = "Parser subnet ID."
  value       = aws_subnet.parser.id
}

output "egress_route_table_id" {
  description = "Egress-compute route table ID; the NAT module adds the default route here."
  value       = aws_route_table.egress.id
}

output "egress_subnet_cidr" {
  description = "Egress-compute subnet CIDR, the only source the NAT instance translates."
  value       = aws_subnet.egress.cidr_block
}

output "parser_security_group_id" {
  description = "Parser security group ID."
  value       = aws_security_group.parser.id
}

output "egress_compute_security_group_id" {
  description = "Egress-compute security group ID."
  value       = aws_security_group.egress_compute.id
}
