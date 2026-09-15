terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket = "fixture-state"
    access_key = "fake-tfhcl-backend-secret"
  }
}

provider "aws" {
  alias = "primary"
  region = "us-east-1"
  secret_key = "fake-tfhcl-provider-secret"
}

resource "aws_s3_bucket" "app" {
  bucket = "fixture-app"
  count = 1
  depends_on = [aws_iam_role.app]
  provider = aws.primary

  lifecycle {
    prevent_destroy = true
  }

  provisioner "local-exec" {
    command = "echo static-only"
  }
}

data "aws_caller_identity" "current" {}

module "vpc" {
  source = "./modules/vpc"
}

module "remote" {
  source = "git::https://user:fake-tfhcl-module-secret@example.invalid/org/mod.git"
}

variable "region" {
  type = string
  default = "us-east-1"
  description = "Deployment region"
  validation {
    condition = true
    error_message = "ok"
  }
}

output "bucket_name" {
  value = aws_s3_bucket.app.id
  sensitive = true
  description = "Bucket name"
}

locals {
  name = "app"
  api_token = "fake-tfhcl-local-secret"
}

moved {
  from = aws_s3_bucket.old
  to = aws_s3_bucket.app
}

import {
  to = aws_s3_bucket.imported
  id = "fake-tfhcl-import-secret"
}

removed {
  from = aws_s3_bucket.legacy
}

check "health" {
  assert {
    condition = true
    error_message = "healthy"
  }
}
