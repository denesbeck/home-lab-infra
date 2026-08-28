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
