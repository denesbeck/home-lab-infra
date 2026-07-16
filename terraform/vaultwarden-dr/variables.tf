variable "aws_region" {
  type    = string
  default = "eu-central-1"
}

variable "s3_backup_bucket" {
  type        = string
  description = "Name of the existing S3 bucket containing Vaultwarden backups"
}

variable "sns_email" {
  type        = string
  description = "Email address for failover notifications"
}

variable "tailscale_api_key" {
  type        = string
  sensitive   = true
  description = "Tailscale API key for generating one-time auth keys"
}

variable "discord_webhook_url" {
  type        = string
  sensitive   = true
  description = "Discord webhook URL for failover notifications"
}

variable "cloudflare_api_token" {
  type        = string
  sensitive   = true
  description = "Cloudflare API token with DNS edit permissions for the failover domain zone"
}

variable "failover_domain" {
  type        = string
  description = "Domain name for the failover instance (e.g. vaultwarden-failover.arcade-lab.io)"
}

variable "cloudflare_zone" {
  type        = string
  description = "Cloudflare zone (root domain, e.g. arcade-lab.io)"
}

variable "ec2_instance_type" {
  type    = string
  default = "t3.micro"
}

variable "failover_ami_id" {
  type        = string
  default     = "ami-036bdae36143a955f"
  description = "Pinned Amazon Linux 2023 AMI for the failover instance (validated end-to-end). Bump deliberately, not automatically."
}

variable "healthcheck_delay_min" {
  type        = number
  default     = 10
  description = "Minutes after launch before verifying the failover instance finished provisioning"
}
