resource "aws_security_group" "failover" {
  name        = "vaultwarden-dr-failover"
  description = "Security group for Vaultwarden failover instance"

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_launch_template" "failover" {
  name                   = "vaultwarden-dr-failover"
  image_id               = var.failover_ami_id
  instance_type          = var.ec2_instance_type
  update_default_version = true

  instance_market_options {
    market_type = "spot"
    spot_options {
      spot_instance_type = "one-time"
    }
  }

  iam_instance_profile {
    name = aws_iam_instance_profile.ec2_failover.name
  }

  vpc_security_group_ids = [aws_security_group.failover.id]

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name                   = "vaultwarden-failover"
      "vaultwarden-failover" = "active"
    }
  }
}
