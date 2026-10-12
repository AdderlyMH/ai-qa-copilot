terraform {
  required_version = ">= 1.16.5, < 2.0.0"
}

variable "project" {
  description = "Project slug used as the first naming segment."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,30}[a-z0-9]$", var.project))
    error_message = "project must be 3-32 lowercase letters, digits or hyphens."
  }
}

variable "environment" {
  description = "Deployment environment."
  type        = string

  validation {
    condition     = contains(["bootstrap", "preview", "production"], var.environment)
    error_message = "environment must be bootstrap, preview or production."
  }
}

variable "extra_tags" {
  description = "Additional tags merged after the standard tags."
  type        = map(string)
  default     = {}
}

locals {
  name_prefix = "${var.project}-${var.environment}"

  tags = merge(
    {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
      Repository  = "AdderlyMH/ai-qa-copilot"
    },
    var.extra_tags,
  )
}

output "name_prefix" {
  description = "Prefix for resource names: <project>-<environment>."
  value       = local.name_prefix
}

output "tags" {
  description = "Standard tags for provider default_tags."
  value       = local.tags
}
