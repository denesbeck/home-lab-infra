variable "aws_region" {
  type    = string
  default = "eu-central-1"
}

variable "monthly_budget_usd" {
  type    = string
  default = "10"
}

variable "budget_alert_email" {
  type = string
}
