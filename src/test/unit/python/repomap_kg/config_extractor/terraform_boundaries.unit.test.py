import json
import unittest

from repomap_kg.extractors.config.generic import extract_config_file_observations
from repomap_kg.extractors.config.terraform_hcl_helpers import (
    _terraform_hcl_bool_literal,
    _terraform_hcl_bounded_string,
    _terraform_hcl_expression_kind,
    _terraform_hcl_literal_string,
)


class ConfigExtractorTerraformBoundariesUnitTests(unittest.TestCase):
    def test_terraform_hcl_import_moved_check_removed_blocks(self):
        hcl_content = """
terraform {
  required_version = var.min_version
  required_providers {
    simple_provider = "hashicorp/simple"
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  backend "s3" {
    bucket = var.state_bucket
  }
}

import {
  to = aws_s3_bucket.imported
  id = "bucket-123"
}

moved {
  from = aws_s3_bucket.old_name
  to   = aws_s3_bucket.new_name
}

check "health_check" {
  data "http" "endpoint" {
    url = "https://example.com/health"
  }
  assert {
    condition     = data.http.endpoint.status_code == 200
    error_message = "endpoint returned non-200"
  }
}

removed {
  from = aws_instance.deprecated
  lifecycle {
    destroy = false
  }
}
"""
        obs = extract_config_file_observations("infra/advanced.tf", hcl_content)
        self.assertEqual(obs[0].kind, "terraform.file")
        kinds = {o.kind for o in obs}
        self.assertIn("terraform.required_version", kinds)
        self.assertIn("terraform.required_provider", kinds)
        self.assertIn("terraform.backend", kinds)
        self.assertIn("terraform.import", kinds)
        self.assertIn("terraform.moved", kinds)
        self.assertIn("terraform.check", kinds)
        self.assertIn("terraform.removed", kinds)

    def test_terraform_json_advanced_blocks(self):
        payload = {
            "terraform": {
                "backend": {
                    "gcs": {
                        "bucket": "state-bucket"
                    }
                },
                "required_version": ">= 1.5.0",
                "required_providers": {
                    "google": {
                        "source": "hashicorp/google",
                        "version": "4.0.0"
                    }
                }
            },
            "resource": {
                "google_storage_bucket": {
                    "static": {
                        "name": "static-assets"
                    }
                }
            },
            "data": {
                "google_client_config": {
                    "default": {}
                }
            }
        }
        obs = extract_config_file_observations(
            "infra/advanced.tf.json",
            json.dumps(payload),
        )
        self.assertEqual(obs[0].kind, "config.document")
        kinds = {o.kind for o in obs}
        self.assertIn("terraform.backend", kinds)
        self.assertIn("terraform.required_version", kinds)
        self.assertIn("terraform.required_provider", kinds)
        self.assertIn("terraform.resource", kinds)
        self.assertIn("terraform.data_source", kinds)

    def test_terraform_hcl_providers_modules_and_variables(self):
        hcl_content = """
provider "aws" {
  alias  = "west"
  region = "us-west-2"
}

variable "db_password" {
  type        = string
  sensitive   = true
  description = "Database admin password"
  default     = null
}

output "connection_string" {
  value     = "db://user:pass@host"
  sensitive = true
}

module "vpc_remote" {
  source = "git::https://github.com/terraform-aws-modules/terraform-aws-vpc.git"
}

module "vpc_ssh" {
  source = "ssh://git@github.com/org/repo.git"
}

module "vpc_relative" {
  source = "./modules/vpc"
}
"""
        obs = extract_config_file_observations("infra/modules.tf", hcl_content)
        self.assertEqual(obs[0].kind, "terraform.file")
        kinds = {o.kind for o in obs}
        self.assertIn("terraform.provider", kinds)
        self.assertIn("terraform.variable", kinds)
        self.assertIn("terraform.output", kinds)
        self.assertIn("terraform.module", kinds)

    def test_terraform_hcl_helpers_boundaries(self):
        self.assertTrue(_terraform_hcl_bool_literal("true"))
        self.assertFalse(_terraform_hcl_bool_literal("false"))
        self.assertIsNone(_terraform_hcl_bool_literal("not-bool"))
        self.assertEqual(_terraform_hcl_literal_string('"literal"'), "literal")
        self.assertIsNone(_terraform_hcl_literal_string("unquoted"))
        self.assertEqual(_terraform_hcl_bounded_string("short"), "short")
        self.assertEqual(_terraform_hcl_bounded_string("a" * 300), "<string:300>")
        self.assertEqual(_terraform_hcl_expression_kind('"literal"'), "literal_string")
        self.assertEqual(_terraform_hcl_expression_kind("${var.foo}"), "template_interpolation")
        self.assertEqual(_terraform_hcl_expression_kind("aws_s3_bucket.app.id"), "traversal_reference")
        self.assertEqual(_terraform_hcl_expression_kind("null"), "literal_null")
        self.assertEqual(_terraform_hcl_expression_kind("[1, 2]"), "collection_shape")


if __name__ == "__main__":
    unittest.main()
