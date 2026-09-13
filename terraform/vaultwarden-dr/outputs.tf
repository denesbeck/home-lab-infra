output "cloudwatch_alarm_arn" {
  value = aws_cloudwatch_metric_alarm.vaultwarden_heartbeat.arn
}

output "sns_alarm_topic_arn" {
  value = aws_sns_topic.vaultwarden_alarm.arn
}

output "sns_notifications_topic_arn" {
  value = aws_sns_topic.vaultwarden_notifications.arn
}

output "lambda_function_arn" {
  value = aws_lambda_function.failover.arn
}

output "launch_template_id" {
  value = aws_launch_template.failover.id
}

output "failover_mode_parameter" {
  value       = aws_ssm_parameter.failover_mode.name
  description = "SSM parameter holding the maintenance switch"
}

output "failover_switch_commands" {
  description = "Copy-paste commands to read and flip the maintenance switch"
  value = {
    status = "aws ssm get-parameter --name ${aws_ssm_parameter.failover_mode.name} --query Parameter.Value --output text"
    # Prefer an expiry over `off`: the window lapses on its own, so a forgotten
    # switch cannot leave the vault without DR indefinitely.
    pause_2h = "aws ssm put-parameter --name ${aws_ssm_parameter.failover_mode.name} --overwrite --value $(date -u -v+2H +%Y-%m-%dT%H:%M:%SZ)"
    resume   = "aws ssm put-parameter --name ${aws_ssm_parameter.failover_mode.name} --overwrite --value auto"
  }
}
