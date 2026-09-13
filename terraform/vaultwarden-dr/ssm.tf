resource "aws_ssm_parameter" "tailscale_oauth_client_id" {
  name  = "/vaultwarden-dr/tailscale-oauth-client-id"
  type  = "SecureString"
  value = var.tailscale_oauth_client_id
}

resource "aws_ssm_parameter" "tailscale_oauth_client_secret" {
  name  = "/vaultwarden-dr/tailscale-oauth-client-secret"
  type  = "SecureString"
  value = var.tailscale_oauth_client_secret
}

resource "aws_ssm_parameter" "discord_webhook_url" {
  name  = "/vaultwarden-dr/discord-webhook-url"
  type  = "SecureString"
  value = var.discord_webhook_url
}

resource "aws_ssm_parameter" "cloudflare_api_token" {
  name  = "/vaultwarden-dr/cloudflare-api-token"
  type  = "SecureString"
  value = var.cloudflare_api_token
}

# Maintenance switch, read by the Lambda on every alarm. `auto` is normal;
# an RFC3339 instant suppresses failover until then; `off` suppresses with no
# expiry. Runtime state, not config — ignore_changes keeps a terraform apply
# from cancelling an in-flight maintenance window (or re-arming one you ended).
resource "aws_ssm_parameter" "failover_mode" {
  name        = "/vaultwarden-dr/failover-mode"
  type        = "String"
  value       = "auto"
  description = "auto | off | RFC3339 instant to suppress failover until"

  lifecycle {
    ignore_changes = [value]
  }
}
