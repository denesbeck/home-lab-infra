data "archive_file" "failover" {
  type        = "zip"
  source_file = "${path.module}/lambda/failover.py"
  output_path = "${path.module}/lambda/failover.zip"
}

resource "aws_lambda_function" "failover" {
  function_name    = "vaultwarden-dr-failover"
  role             = aws_iam_role.lambda_failover.arn
  handler          = "failover.handler"
  runtime          = "python3.12"
  timeout          = 60
  filename         = data.archive_file.failover.output_path
  source_code_hash = data.archive_file.failover.output_base64sha256

  environment {
    variables = {
      LAUNCH_TEMPLATE_ID    = aws_launch_template.failover.id
      SSM_TAILSCALE_KEY     = aws_ssm_parameter.tailscale_api_key.name
      SSM_DISCORD_WEBHOOK   = aws_ssm_parameter.discord_webhook_url.name
      S3_BACKUP_BUCKET      = var.s3_backup_bucket
      SNS_NOTIFICATIONS_ARN = aws_sns_topic.vaultwarden_notifications.arn
      FAILOVER_DOMAIN       = var.failover_domain
      NOTIFICATION_EMAIL    = var.sns_email
      CF_ZONE               = var.cloudflare_zone
      SCHEDULER_ROLE_ARN    = aws_iam_role.scheduler_invoke.arn
      HEALTHCHECK_DELAY_MIN = tostring(var.healthcheck_delay_min)
    }
  }
}

resource "aws_lambda_permission" "sns" {
  statement_id  = "AllowSNSInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.failover.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.vaultwarden_alarm.arn
}
