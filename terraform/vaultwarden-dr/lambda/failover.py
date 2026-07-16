import base64
import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

import boto3


ec2 = boto3.client("ec2")
ssm = boto3.client("ssm")
sns = boto3.client("sns")
s3 = boto3.client("s3")
scheduler = boto3.client("scheduler")


def handler(event, context):
    # Delayed health-check invocation (from EventBridge Scheduler).
    if isinstance(event, dict) and event.get("action") == "healthcheck":
        return _handle_healthcheck(event)

    message = json.loads(event["Records"][0]["Sns"]["Message"])
    state = message.get("NewStateValue")

    if state == "ALARM":
        return _handle_failover(context)
    elif state == "OK":
        return _handle_teardown()
    else:
        print(f"Ignoring state: {state}")
        return


def _handle_failover(context):
    if _find_failover_instance():
        print("Failover instance already running, skipping")
        return

    tailscale_key = _get_ssm_param(os.environ["SSM_TAILSCALE_KEY"])
    discord_webhook = _get_ssm_param(os.environ["SSM_DISCORD_WEBHOOK"])
    tailscale_auth_key = _create_tailscale_auth_key(tailscale_key)

    user_data = _build_user_data(
        tailscale_auth_key=tailscale_auth_key,
        discord_webhook=discord_webhook,
        s3_bucket=os.environ["S3_BACKUP_BUCKET"],
    )

    response = ec2.run_instances(
        LaunchTemplate={"LaunchTemplateId": os.environ["LAUNCH_TEMPLATE_ID"]},
        MinCount=1,
        MaxCount=1,
        UserData=user_data,
    )

    instance_id = response["Instances"][0]["InstanceId"]
    print(f"Launched failover instance: {instance_id}")

    # Schedule an independent check that the instance actually finished
    # provisioning. If user-data dies silently (hang / signal / crash), the
    # instance never writes its readiness marker and this catches it.
    _schedule_healthcheck(instance_id, context.invoked_function_arn)

    alert_msg = (
        f"[Vaultwarden DR] Failover triggered.\n\n"
        f"The on-prem server has been unreachable for 3+ minutes. "
        f"A failover EC2 instance ({instance_id}) is launching with the latest S3 backup.\n\n"
        f"Once ready, it will be accessible at https://{os.environ['FAILOVER_DOMAIN']}.\n\n"
        f"The instance will be automatically terminated when heartbeat recovers for 3+ minutes."
    )

    _notify_sns("Vaultwarden DR - Failover Triggered", alert_msg)
    _notify_discord(
        discord_webhook,
        f"**[Vaultwarden DR]** Failover triggered. EC2 instance `{instance_id}` is launching with the latest backup.",
    )

    return {"instance_id": instance_id}


def _handle_teardown():
    instance_id = _find_failover_instance()
    if not instance_id:
        print("No failover instance found, nothing to tear down")
        return

    print(f"Terminating failover instance: {instance_id}")
    ec2.terminate_instances(InstanceIds=[instance_id])

    discord_webhook = _get_ssm_param(os.environ["SSM_DISCORD_WEBHOOK"])

    alert_msg = (
        f"[Vaultwarden DR] Recovery detected.\n\n"
        f"The on-prem server has been sending heartbeats for 3+ consecutive minutes. "
        f"Failover instance ({instance_id}) has been terminated automatically."
    )

    _notify_sns("Vaultwarden DR - Recovery Complete", alert_msg)
    _notify_discord(
        discord_webhook,
        f"**[Vaultwarden DR]** Recovery detected. Failover instance `{instance_id}` terminated automatically.",
    )

    return {"terminated_instance": instance_id}


def _handle_healthcheck(event):
    instance_id = event["instance_id"]
    bucket = os.environ["S3_BACKUP_BUCKET"]
    delay = os.environ.get("HEALTHCHECK_DELAY_MIN", "10")

    if _ready_marker_exists(instance_id):
        print(f"Health check OK: {instance_id} reported ready")
        return {"status": "ready", "instance_id": instance_id}

    state = _instance_state(instance_id)
    if state not in ("pending", "running"):
        # Instance was torn down (fast recovery) or never persisted -> not an
        # outage of the failover itself. Stay quiet to avoid false alarms.
        print(f"Instance {instance_id} inactive (state={state}); no alert")
        return {"status": "inactive", "state": state, "instance_id": instance_id}

    log_path = f"s3://{bucket}/failover-logs/{instance_id}.log"
    print(f"Health check FAILED: {instance_id} is {state} but never reported ready")

    discord_webhook = _get_ssm_param(os.environ["SSM_DISCORD_WEBHOOK"])
    alert_msg = (
        f"[Vaultwarden DR] Failover health check FAILED.\n\n"
        f"Instance {instance_id} is '{state}' but did not finish provisioning "
        f"within {delay} minutes. The failover site may be unavailable at "
        f"https://{os.environ['FAILOVER_DOMAIN']}.\n\n"
        f"Investigate the user-data log: {log_path}"
    )
    _notify_sns("Vaultwarden DR - Failover Health Check FAILED", alert_msg)
    _notify_discord(
        discord_webhook,
        f"**[Vaultwarden DR]** ⚠️ Health check FAILED: instance `{instance_id}` "
        f"({state}) did not finish provisioning within {delay} min. Log: `{log_path}`",
    )
    return {"status": "unhealthy", "state": state, "instance_id": instance_id}


def _schedule_healthcheck(instance_id, function_arn):
    delay = int(os.environ.get("HEALTHCHECK_DELAY_MIN", "10"))
    run_at = (datetime.now(timezone.utc) + timedelta(minutes=delay)).strftime(
        "at(%Y-%m-%dT%H:%M:%S)"
    )
    try:
        scheduler.create_schedule(
            Name=f"vw-dr-healthcheck-{instance_id}",
            FlexibleTimeWindow={"Mode": "OFF"},
            ScheduleExpression=run_at,
            ScheduleExpressionTimezone="UTC",
            ActionAfterCompletion="DELETE",
            Target={
                "Arn": function_arn,
                "RoleArn": os.environ["SCHEDULER_ROLE_ARN"],
                "Input": json.dumps({"action": "healthcheck", "instance_id": instance_id}),
            },
        )
        print(f"Scheduled health check for {instance_id} at {run_at} UTC")
    except Exception as e:
        # Never let a scheduling failure abort the actual failover launch.
        print(f"Failed to schedule health check: {e}")


def _ready_marker_exists(instance_id):
    try:
        s3.head_object(
            Bucket=os.environ["S3_BACKUP_BUCKET"],
            Key=f"failover-status/{instance_id}.ready",
        )
        return True
    except Exception:
        return False


def _instance_state(instance_id):
    try:
        response = ec2.describe_instances(InstanceIds=[instance_id])
    except Exception:
        return None
    for r in response["Reservations"]:
        for i in r["Instances"]:
            return i["State"]["Name"]
    return None


def _find_failover_instance():
    response = ec2.describe_instances(
        Filters=[
            {"Name": "tag:vaultwarden-failover", "Values": ["active"]},
            {"Name": "instance-state-name", "Values": ["pending", "running"]},
        ]
    )
    instances = [
        i for r in response["Reservations"] for i in r["Instances"]
    ]
    return instances[0]["InstanceId"] if instances else None


def _get_ssm_param(name):
    response = ssm.get_parameter(Name=name, WithDecryption=True)
    return response["Parameter"]["Value"]


def _create_tailscale_auth_key(api_key):
    data = json.dumps({
        "capabilities": {
            "devices": {
                "create": {
                    "reusable": False,
                    "ephemeral": True,
                    "tags": ["tag:failover"],
                }
            }
        },
        "expirySeconds": 3600,
    }).encode()

    req = urllib.request.Request(
        "https://api.tailscale.com/api/v2/tailnet/-/keys",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())["key"]
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"Tailscale API error {e.code}: {body}")
        raise


def _build_user_data(tailscale_auth_key, discord_webhook, s3_bucket):
    script = USER_DATA_TEMPLATE.replace("{{TAILSCALE_AUTH_KEY}}", tailscale_auth_key)
    script = script.replace("{{DISCORD_WEBHOOK_URL}}", discord_webhook)
    script = script.replace("{{S3_BACKUP_BUCKET}}", s3_bucket)
    script = script.replace("{{FAILOVER_DOMAIN}}", os.environ["FAILOVER_DOMAIN"])
    script = script.replace("{{NOTIFICATION_EMAIL}}", os.environ["NOTIFICATION_EMAIL"])
    script = script.replace("{{CF_ZONE}}", os.environ["CF_ZONE"])

    return base64.b64encode(script.encode()).decode()


USER_DATA_TEMPLATE = r"""#!/bin/bash

TAILSCALE_AUTH_KEY="{{TAILSCALE_AUTH_KEY}}"
DISCORD_WEBHOOK_URL="{{DISCORD_WEBHOOK_URL}}"
S3_BACKUP_BUCKET="{{S3_BACKUP_BUCKET}}"
FAILOVER_DOMAIN="{{FAILOVER_DOMAIN}}"
NOTIFICATION_EMAIL="{{NOTIFICATION_EMAIL}}"

exec > /var/log/user-data.log 2>&1

# Resolve our own instance id up front (IMDSv2) so logs/markers are keyed by it.
IMDS_TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
INSTANCE_ID=$(curl -s -H "X-aws-ec2-metadata-token: $IMDS_TOKEN" http://169.254.169.254/latest/meta-data/instance-id)
REGION=$(curl -s -H "X-aws-ec2-metadata-token: $IMDS_TOKEN" http://169.254.169.254/latest/meta-data/placement/region)

LOG_KEY="failover-logs/${INSTANCE_ID}.log"

flush_log() {
    aws s3 cp /var/log/user-data.log "s3://${S3_BACKUP_BUCKET}/${LOG_KEY}" >/dev/null 2>&1 || true
}

notify_discord() {
    curl -s -H "Content-Type: application/json" \
        -d "{\"content\": \"$1\"}" \
        "$DISCORD_WEBHOOK_URL" || true
}

# Continuously ship the log to S3 so it survives ANY death (error, hang that
# trips the cloud-final service timeout, spot reclaim, SIGKILL). The on-error
# handler used to be the only uploader, so a signal-kill lost the log entirely.
( while true; do flush_log; sleep 15; done ) &
LOG_SHIPPER_PID=$!

on_error() {
    notify_discord "**[Vaultwarden DR]** User-data FAILED at line $1 (instance \`$INSTANCE_ID\`). Log: \`s3://${S3_BACKUP_BUCKET}/${LOG_KEY}\`"
    flush_log
}

on_signal() {
    notify_discord "**[Vaultwarden DR]** User-data was KILLED by a signal before completing (instance \`$INSTANCE_ID\`). Log: \`s3://${S3_BACKUP_BUCKET}/${LOG_KEY}\`"
    flush_log
    exit 143
}

trap 'on_error $LINENO' ERR
trap on_signal TERM INT

set -euo pipefail

# Guard hang-prone steps with timeouts: a hang otherwise stalls until the
# service is killed with no ERR trap. With `timeout`, a stall becomes a normal
# non-zero exit that the ERR trap reports.
timeout 300 dnf install -y docker nginx sqlite unzip tar gzip

systemctl enable docker
systemctl start docker

curl -fsSL https://tailscale.com/install.sh | sh
timeout 120 tailscale up --authkey="$TAILSCALE_AUTH_KEY" --hostname=vaultwarden-failover

LATEST_BACKUP=$(aws s3api list-objects-v2 \
    --bucket "$S3_BACKUP_BUCKET" \
    --prefix "vaultwarden_" \
    --query 'sort_by(Contents, &LastModified)[-1].Key' \
    --output text)

if [ -z "$LATEST_BACKUP" ] || [ "$LATEST_BACKUP" = "None" ]; then
    notify_discord "Vaultwarden failover FAILED: no backups found in S3."
    exit 1
fi

mkdir -p /tmp/vaultwarden-restore
aws s3 cp "s3://$S3_BACKUP_BUCKET/$LATEST_BACKUP" /tmp/vaultwarden-restore/backup.tar.gz
tar -xzf /tmp/vaultwarden-restore/backup.tar.gz -C /tmp/vaultwarden-restore

mkdir -p /home/vaultwarden
mv /tmp/vaultwarden-restore/data /home/vaultwarden/data
rm -rf /tmp/vaultwarden-restore

TAILSCALE_IP=$(tailscale ip -4)

CF_TOKEN=$(aws ssm get-parameter --name "/vaultwarden-dr/cloudflare-api-token" --with-decryption --region "$REGION" --query 'Parameter.Value' --output text)

CF_ZONE_ID=$(curl -s -X GET "https://api.cloudflare.com/client/v4/zones?name={{CF_ZONE}}" \
    -H "Authorization: Bearer $CF_TOKEN" \
    -H "Content-Type: application/json" | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"][0]["id"])')

CF_RECORD=$(curl -s -X GET "https://api.cloudflare.com/client/v4/zones/$CF_ZONE_ID/dns_records?type=A&name=$FAILOVER_DOMAIN" \
    -H "Authorization: Bearer $CF_TOKEN" \
    -H "Content-Type: application/json")

CF_RECORD_ID=$(echo "$CF_RECORD" | python3 -c 'import sys,json; r=json.load(sys.stdin)["result"]; print(r[0]["id"] if r else "")')

if [ -n "$CF_RECORD_ID" ]; then
    curl -s -X PUT "https://api.cloudflare.com/client/v4/zones/$CF_ZONE_ID/dns_records/$CF_RECORD_ID" \
        -H "Authorization: Bearer $CF_TOKEN" \
        -H "Content-Type: application/json" \
        --data "{\"type\":\"A\",\"name\":\"$FAILOVER_DOMAIN\",\"content\":\"$TAILSCALE_IP\",\"ttl\":60,\"proxied\":false}"
else
    curl -s -X POST "https://api.cloudflare.com/client/v4/zones/$CF_ZONE_ID/dns_records" \
        -H "Authorization: Bearer $CF_TOKEN" \
        -H "Content-Type: application/json" \
        --data "{\"type\":\"A\",\"name\":\"$FAILOVER_DOMAIN\",\"content\":\"$TAILSCALE_IP\",\"ttl\":60,\"proxied\":false}"
fi

timeout 120 dnf install -y python3-pip
timeout 300 pip3 install certbot certbot-dns-cloudflare

mkdir -p /root/.secrets
cat > /root/.secrets/cloudflare.ini <<CFEOF
dns_cloudflare_api_token = $CF_TOKEN
CFEOF
chmod 600 /root/.secrets/cloudflare.ini

timeout 180 certbot certonly \
    --dns-cloudflare \
    --dns-cloudflare-credentials /root/.secrets/cloudflare.ini \
    --dns-cloudflare-propagation-seconds 30 \
    -d "$FAILOVER_DOMAIN" \
    --non-interactive --agree-tos --email "$NOTIFICATION_EMAIL"

rm -rf /root/.secrets

docker run -d \
    --name vaultwarden \
    --restart always \
    -v /home/vaultwarden/data:/data \
    -p 127.0.0.1:8080:80 \
    -e DOMAIN="https://$FAILOVER_DOMAIN" \
    -e SIGNUPS_ALLOWED=false \
    -e INVITATIONS_ALLOWED=false \
    -e SHOW_PASSWORD_HINT=false \
    vaultwarden/server:latest

cat > /etc/nginx/conf.d/vaultwarden.conf <<NGINXEOF
server {
    listen 443 ssl;
    server_name $FAILOVER_DOMAIN;

    ssl_certificate /etc/letsencrypt/live/$FAILOVER_DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$FAILOVER_DOMAIN/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }

    location /notifications/hub {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
NGINXEOF

systemctl restart nginx

# Signal success to the health-check Lambda, then send the ready notification.
echo "ready $(date -u +%FT%TZ) $INSTANCE_ID" | \
    aws s3 cp - "s3://${S3_BACKUP_BUCKET}/failover-status/${INSTANCE_ID}.ready" || true

kill "$LOG_SHIPPER_PID" 2>/dev/null || true
flush_log

notify_discord "Vaultwarden failover ready at \`https://$FAILOVER_DOMAIN\`. Backup restored: \`$LATEST_BACKUP\`. Tailscale IP: \`$TAILSCALE_IP\`"
"""


def _notify_sns(subject, message):
    sns.publish(
        TopicArn=os.environ["SNS_NOTIFICATIONS_ARN"],
        Subject=subject,
        Message=message,
    )


def _notify_discord(webhook_url, message):
    data = json.dumps({"content": message}).encode()
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "VaultwardenDR/1.0",
        },
    )
    try:
        urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"Failed to notify Discord: {e.code} {body}")
    except urllib.error.URLError as e:
        print(f"Failed to notify Discord: {e}")
