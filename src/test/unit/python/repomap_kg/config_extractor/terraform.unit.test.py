import json
import unittest


from repomap_kg.extractors.config.generic import (
    extract_config_file_observations,
)


class ConfigExtractorTerraformUnitTests(unittest.TestCase):
    def test_terraform_json_emits_static_profile_observations_and_references(self):
        observations = extract_config_file_observations(
            "infra/main.tf.json",
            json.dumps(
                {
                    "terraform": {
                        "required_version": ">= 1.6.0",
                        "required_providers": {
                            "aws": {
                                "source": "hashicorp/aws",
                                "version": "~> 5.0",
                            }
                        },
                        "backend": {
                            "s3": {
                                "bucket": "example-state",
                                "key": "state/app.tfstate",
                            }
                        },
                    },
                    "provider": {"aws": {"region": "us-east-1"}},
                    "resource": {
                        "aws_s3_bucket": {
                            "app": {
                                "bucket": "example-app",
                                "secret_key": "fake-terraform-secret",
                            }
                        }
                    },
                    "data": {"aws_caller_identity": {"current": {}}},
                    "module": {"vpc": {"source": "terraform-aws-modules/vpc/aws"}},
                    "variable": {"region": {"type": "string"}},
                    "output": {"bucket_name": {"value": "${aws_s3_bucket.app.id}"}},
                    "locals": {"name": "app"},
                }
            ),
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        kinds = {observation.kind for observation in observations}
        references = [item for item in observations if item.kind == "terraform.reference"]
        resource = next(item for item in observations if item.kind == "terraform.resource")
        required_provider = next(
            item for item in observations if item.kind == "terraform.required_provider"
        )

        self.assertTrue(
            {
                "terraform.file",
                "terraform.required_version",
                "terraform.required_provider",
                "terraform.backend",
                "terraform.provider",
                "terraform.resource",
                "terraform.data_source",
                "terraform.module",
                "terraform.variable",
                "terraform.output",
                "terraform.local",
                "terraform.reference",
            }.issubset(kinds)
        )
        self.assertEqual(resource.metadata["resource_type"], "aws_s3_bucket")
        self.assertEqual(resource.metadata["resource_name"], "app")
        self.assertEqual(required_provider.metadata["provider_source"], "hashicorp/aws")
        self.assertIn(
            ("provider_source", "external:terraform.provider:hashicorp%2Faws"),
            {
                (item.metadata["reference_kind"], item.target)
                for item in references
            },
        )
        self.assertIn(
            ("module_source", "external:terraform.module:terraform-aws-modules%2Fvpc%2Faws"),
            {
                (item.metadata["reference_kind"], item.target)
                for item in references
            },
        )
        self.assertNotIn("fake-terraform-secret", payload)

    def test_terraform_tfvars_json_redacts_all_values_by_default(self):
        observations = extract_config_file_observations(
            "terraform.tfvars.json",
            json.dumps(
                {
                    "region": "us-east-1",
                    "replicas": 3,
                    "tags": {"service": "api"},
                    "db_password": "fake-tfvars-secret",
                }
            ),
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        variables = [item for item in observations if item.kind == "terraform.variable"]
        paths = {item.metadata["pointer"]: item for item in observations if item.kind == "config.path"}

        self.assertEqual({item.metadata["variable_name"] for item in variables}, {"region", "replicas", "tags", "db_password"})
        self.assertTrue(all(item.metadata["redacted"] for item in variables))
        self.assertEqual(
            {item.metadata["value_type"] for item in variables},
            {"string", "number", "object"},
        )
        self.assertTrue(paths["/region"].metadata["redacted"])
        self.assertTrue(paths["/tags"].metadata["redacted"])
        self.assertNotIn("us-east-1", payload)
        self.assertNotIn("api", payload)
        self.assertNotIn("fake-tfvars-secret", payload)

    def test_terraform_hcl_emits_static_profile_observations_and_references(self):
        observations = extract_config_file_observations(
            "infra/main.tf",
            """
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
""",
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        kinds = {observation.kind for observation in observations}
        references = [item for item in observations if item.kind == "terraform.reference"]
        resource = next(item for item in observations if item.kind == "terraform.resource")
        local_module = next(
            item
            for item in observations
            if item.kind == "terraform.module"
            and item.metadata["module_name"] == "vpc"
        )
        remote_module = next(
            item
            for item in observations
            if item.kind == "terraform.module"
            and item.metadata["module_name"] == "remote"
        )
        variable = next(item for item in observations if item.kind == "terraform.variable")
        output = next(item for item in observations if item.kind == "terraform.output")

        self.assertTrue(
            {
                "terraform.file",
                "terraform.block",
                "terraform.required_version",
                "terraform.required_provider",
                "terraform.backend",
                "terraform.provider",
                "terraform.resource",
                "terraform.data_source",
                "terraform.module",
                "terraform.variable",
                "terraform.output",
                "terraform.local",
                "terraform.reference",
                "terraform.moved",
                "terraform.import",
                "terraform.removed",
                "terraform.check",
                "terraform.redaction",
            }.issubset(kinds)
        )
        self.assertEqual(resource.metadata["resource_type"], "aws_s3_bucket")
        self.assertEqual(resource.metadata["resource_name"], "app")
        self.assertEqual(resource.metadata["provider_prefix"], "aws")
        self.assertTrue(resource.metadata["count_present"])
        self.assertTrue(resource.metadata["lifecycle_present"])
        self.assertTrue(resource.metadata["provisioner_present"])
        self.assertEqual(local_module.target, "file:infra/modules/vpc")
        self.assertTrue(remote_module.metadata["not_fetched"])
        self.assertTrue(remote_module.metadata["redacted"])
        self.assertEqual(variable.metadata["variable_name"], "region")
        self.assertTrue(variable.metadata["default_present"])
        self.assertEqual(variable.metadata["default_value_type"], "string")
        self.assertTrue(variable.metadata["validation_present"])
        self.assertEqual(output.metadata["value_expression_kind"], "traversal_reference")
        self.assertIn(
            ("provider_source", "external:terraform.provider:hashicorp%2Faws"),
            {
                (item.metadata["reference_kind"], item.target)
                for item in references
            },
        )
        self.assertIn(
            ("module_source_local", "file:infra/modules/vpc"),
            {
                (item.metadata["reference_kind"], item.target)
                for item in references
            },
        )
        self.assertIn(
            ("depends_on", "external:terraform.reference:aws_iam_role.app"),
            {
                (item.metadata["reference_kind"], item.target)
                for item in references
            },
        )
        self.assertNotIn("fake-tfhcl-backend-secret", payload)
        self.assertNotIn("fake-tfhcl-provider-secret", payload)
        self.assertNotIn("fake-tfhcl-module-secret", payload)
        self.assertNotIn("fake-tfhcl-local-secret", payload)
        self.assertNotIn("fake-tfhcl-import-secret", payload)

    def test_terraform_hcl_tfvars_redacts_all_values_by_default(self):
        observations = extract_config_file_observations(
            "prod.auto.tfvars",
            """
region = "us-east-1"
replicas = 3
tags = {
  service = "api"
}
names = ["api", "worker"]
db_password = "fake-tfhcl-tfvars-secret"
""",
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        variables = [item for item in observations if item.kind == "terraform.variable"]

        self.assertEqual(
            {item.metadata["variable_name"] for item in variables},
            {"region", "replicas", "tags", "names", "db_password"},
        )
        self.assertTrue(all(item.metadata["redacted"] for item in variables))
        self.assertEqual(
            {
                (item.metadata["variable_name"], item.metadata["value_type"])
                for item in variables
            },
            {
                ("region", "string"),
                ("replicas", "number"),
                ("tags", "object"),
                ("names", "array"),
                ("db_password", "string"),
            },
        )
        self.assertIn("terraform.redaction", {item.kind for item in observations})
        self.assertNotIn("us-east-1", payload)
        self.assertNotIn("api", payload)
        self.assertNotIn("worker", payload)
        self.assertNotIn("fake-tfhcl-tfvars-secret", payload)

    def test_terraform_hcl_parse_errors_and_limits_are_safe(self):
        malformed = extract_config_file_observations(
            "broken.tf",
            'resource "aws_s3_bucket" "broken" {\n  bucket = "fixture"\n',
        )
        limited = extract_config_file_observations(
            "too-many.tf",
            "\n".join(f'variable "v{index}" {{}}' for index in range(260)),
        )

        malformed_errors = [
            item for item in malformed if item.kind == "terraform.parse_error"
        ]
        limited_errors = [
            item for item in limited if item.kind == "terraform.parse_error"
        ]

        self.assertTrue(
            any(
                item.metadata["error_kind"] == "terraform-unclosed-block"
                for item in malformed_errors
            )
        )
        self.assertTrue(
            any(
                item.metadata["error_kind"] == "terraform-block-limit"
                for item in limited_errors
            )
        )
