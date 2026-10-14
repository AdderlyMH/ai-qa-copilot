terraform {
  required_version = ">= 1.16.5, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.68.0, < 7.0.0"
    }
  }
}

# INFRA-002 stage 2: the ADR-017 NAT instance. One t4g.nano in the public
# subnet, configured at first boot from the stock Amazon Linux 2023 arm64 AMI
# (iptables MASQUERADE and IP forwarding, as in the AWS NAT instance guide).
#
# A persistent network interface carries the security group, the disabled
# source/destination check, the Elastic IP and the egress default route, so
# replacing the instance keeps the route target and the public address.
# Because that interface can attach to only one instance, replacement is
# destroy-then-create (create_before_destroy is not used): egress stops for
# the minutes the new instance needs to boot. See the replacement runbook in
# docs/INFRASTRUCTURE.md.
#
# SG-08 is still NOT met: the NAT instance forwards HTTPS to any destination.
# INFRA-004 owns the executor egress control.

variable "name_prefix" {
  description = "Resource name prefix from the naming module."
  type        = string
}

variable "vpc_id" {
  description = "VPC ID."
  type        = string
}

variable "public_subnet_id" {
  description = "Public subnet ID for the NAT instance."
  type        = string
}

variable "egress_route_table_id" {
  description = "Egress-compute route table that receives the default route."
  type        = string
}

variable "egress_subnet_cidr" {
  description = "Egress-compute subnet CIDR; the only source that is forwarded and translated."
  type        = string
}

variable "egress_compute_security_group_id" {
  description = "Security group of the API, worker and executor functions."
  type        = string
}

variable "instance_type" {
  description = "NAT instance type (ADR-017: t4g.nano)."
  type        = string
  default     = "t4g.nano"

  validation {
    condition     = can(regex("^t4g\\.", var.instance_type))
    error_message = "instance_type must be an Arm t4g type to match the arm64 AMI."
  }
}

variable "root_volume_size_gb" {
  description = "Encrypted gp3 root volume size in GB."
  type        = number
  default     = 8

  validation {
    condition     = var.root_volume_size_gb >= 8 && var.root_volume_size_gb <= 30
    error_message = "root_volume_size_gb must be between 8 and 30."
  }
}

variable "ami_ssm_parameter" {
  description = "Public SSM parameter that resolves to the latest Amazon Linux 2023 arm64 AMI."
  type        = string
  default     = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

variable "replacement_generation" {
  description = "Change this value (for example to the date) to replace the instance with the current AMI. See the monthly replacement runbook."
  type        = string
}

data "aws_partition" "current" {}

data "aws_ssm_parameter" "ami" {
  name = var.ami_ssm_parameter
}

locals {
  user_data = <<-EOT
    #!/bin/bash
    # NAT configuration from the AWS NAT instance guide, applied at first boot.
    set -euo pipefail
    EGRESS_CIDR="${var.egress_subnet_cidr}"

    # Package repositories are reachable only after the Elastic IP is
    # associated, so retry for up to ten minutes.
    for attempt in $(seq 1 60); do
      if dnf -y install iptables-services; then
        break
      fi
      sleep 10
    done

    cat > /etc/sysctl.d/90-nat-forwarding.conf <<'CONF'
    net.ipv4.ip_forward=1
    CONF
    sysctl -p /etc/sysctl.d/90-nat-forwarding.conf

    IFACE="$(ip -o -4 route show to default | awk '{print $5}' | head -n 1)"

    systemctl enable --now iptables
    iptables -t nat -F POSTROUTING
    iptables -t nat -A POSTROUTING -o "$IFACE" -s "$EGRESS_CIDR" -j MASQUERADE
    iptables -F FORWARD
    iptables -P FORWARD DROP
    iptables -A FORWARD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
    iptables -A FORWARD -i "$IFACE" -s "$EGRESS_CIDR" -p tcp --dport 443 -j ACCEPT
    service iptables save
  EOT
}

# NAT security group: HTTPS in from the egress-compute functions only, HTTPS
# out. Amazon DNS, the Amazon Time Sync Service and instance metadata are not
# filtered by security groups, so no DNS or NTP rule is needed; package
# repositories and the SSM agent use HTTPS.
resource "aws_security_group" "nat" {
  name        = "${var.name_prefix}-nat-instance"
  description = "NAT instance: HTTPS from egress-compute only, HTTPS out"
  vpc_id      = var.vpc_id

  tags = {
    Name = "${var.name_prefix}-nat-instance"
  }
}

resource "aws_vpc_security_group_ingress_rule" "nat_https_from_egress_compute" {
  security_group_id            = aws_security_group.nat.id
  description                  = "HTTPS from egress-compute functions"
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
  referenced_security_group_id = var.egress_compute_security_group_id
}

resource "aws_vpc_security_group_egress_rule" "nat_https_out" {
  security_group_id = aws_security_group.nat.id
  description       = "Forwarded HTTPS, package repositories and SSM agent"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_network_interface" "nat" {
  subnet_id         = var.public_subnet_id
  security_groups   = [aws_security_group.nat.id]
  source_dest_check = false
  description       = "NAT instance primary interface (route target and Elastic IP holder)"

  tags = {
    Name = "${var.name_prefix}-nat-eni"
  }
}

resource "aws_eip" "nat" {
  #checkov:skip=CKV2_AWS_19:The EIP is attached to the NAT instance's persistent primary network interface through aws_eip_association, so it survives instance replacement; the check recognises only instance-based associations.
  domain = "vpc"

  tags = {
    Name = "${var.name_prefix}-nat-eip"
  }
}

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "nat" {
  name               = "${var.name_prefix}-nat-instance"
  description        = "NAT instance: Session Manager access only"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "nat_ssm_core" {
  role       = aws_iam_role.nat.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "nat" {
  name = "${var.name_prefix}-nat-instance"
  role = aws_iam_role.nat.name
}

# Changing replacement_generation replaces the instance on the next apply.
resource "terraform_data" "replacement_generation" {
  input = var.replacement_generation
}

resource "aws_instance" "nat" {
  #checkov:skip=CKV_AWS_126:Detailed monitoring adds per-metric CloudWatch charges; basic five-minute status and CPU metrics are enough for one low-traffic NAT instance (ADR-017 cost target).
  ami                  = nonsensitive(data.aws_ssm_parameter.ami.insecure_value)
  instance_type        = var.instance_type
  iam_instance_profile = aws_iam_instance_profile.nat.name
  ebs_optimized        = true
  monitoring           = false
  user_data            = local.user_data

  primary_network_interface {
    network_interface_id = aws_network_interface.nat.id
  }

  credit_specification {
    cpu_credits = "standard"
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  maintenance_options {
    auto_recovery = "default"
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_size_gb
    encrypted             = true
    delete_on_termination = true
  }

  tags = {
    Name = "${var.name_prefix}-nat-instance"
  }

  lifecycle {
    # A newer AMI in the SSM parameter does not replace the instance by
    # itself; replacement happens only when replacement_generation changes.
    #
    # source_dest_check is set to false on the persistent network interface.
    # With primary_network_interface, the provider reads the instance value
    # (false) but the argument defaults to true, conflicts with
    # primary_network_interface and its diff is suppressed only for the
    # deprecated network_interface block. Without ignoring it, a plan
    # proposes false -> true and the apply would re-enable the check on the
    # interface, which breaks NAT forwarding.
    ignore_changes       = [ami, user_data, source_dest_check]
    replace_triggered_by = [terraform_data.replacement_generation]
  }
}

resource "aws_eip_association" "nat" {
  allocation_id        = aws_eip.nat.id
  network_interface_id = aws_network_interface.nat.id

  depends_on = [aws_instance.nat]
}

resource "aws_route" "egress_default" {
  route_table_id         = var.egress_route_table_id
  destination_cidr_block = "0.0.0.0/0"
  network_interface_id   = aws_network_interface.nat.id
}

output "nat_instance_id" {
  description = "NAT instance ID."
  value       = aws_instance.nat.id
}

output "nat_public_ip" {
  description = "Elastic IP used for all egress through the NAT instance."
  value       = aws_eip.nat.public_ip
}

output "nat_network_interface_id" {
  description = "Persistent NAT network interface (egress route target)."
  value       = aws_network_interface.nat.id
}
