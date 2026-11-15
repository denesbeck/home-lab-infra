resource "random_id" "state_bucket_suffix" {
  byte_length = 8
}

resource "aws_s3_bucket" "terraform_state" {
  bucket = "home-lab-terraform-state-${random_id.state_bucket_suffix.hex}"
}

resource "aws_s3_bucket_versioning" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket" "vaultwarden_backup" {
  bucket = "vaultwarden-backup-${random_id.state_bucket_suffix.hex}"
}

resource "aws_s3_bucket_public_access_block" "vaultwarden_backup" {
  bucket = aws_s3_bucket.vaultwarden_backup.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "vaultwarden_backup" {
  bucket = aws_s3_bucket.vaultwarden_backup.id

  rule {
    id     = "expire-old-backups"
    status = "Enabled"

    filter {}

    expiration {
      days = 3
    }
  }
}

# Off-site copy of /mnt/photos and /mnt/private.
resource "aws_s3_bucket" "offsite_backup" {
  bucket = "home-lab-offsite-backup-${random_id.state_bucket_suffix.hex}"
}

resource "aws_s3_bucket_public_access_block" "offsite_backup" {
  bucket = aws_s3_bucket.offsite_backup.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# The uploader cannot delete, only overwrite; versioning keeps what it overwrote.
resource "aws_s3_bucket_versioning" "offsite_backup" {
  bucket = aws_s3_bucket.offsite_backup.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "offsite_backup" {
  bucket = aws_s3_bucket.offsite_backup.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "offsite_backup" {
  bucket = aws_s3_bucket.offsite_backup.id

  depends_on = [aws_s3_bucket_versioning.offsite_backup]

  # 180d = Deep Archive's minimum storage charge.
  rule {
    id     = "expire-overwritten-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 180
    }
  }

  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_s3_bucket_policy" "offsite_backup" {
  bucket = aws_s3_bucket.offsite_backup.id

  depends_on = [aws_s3_bucket_public_access_block.offsite_backup]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.offsite_backup.arn,
          "${aws_s3_bucket.offsite_backup.arn}/*",
        ]
        Condition = {
          Bool = { "aws:SecureTransport" = "false" }
        }
      }
    ]
  })
}
