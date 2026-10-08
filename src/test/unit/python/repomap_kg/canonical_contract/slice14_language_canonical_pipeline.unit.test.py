"""Migrated Slice14 isolated controls; zero new integration credit."""

from __future__ import annotations
import unittest
from repomap_kg.extractors.config.terraform_hcl_helpers import _terraform_hcl_module_source


class Slice14LanguageCanonicalPipelineUnitTests(unittest.TestCase):
    def test_s14_a07_terraform_credentialed_module_source_redaction(self) -> None:
        """Terraform module source with embedded credentials is fully redacted."""
        meta, target, rel = _terraform_hcl_module_source(
            "main.tf",
            "git::https://robot_user:super_secret@github.com/corp/security-module.git",
        )
        self.assertEqual(rel, "module_source")
        self.assertTrue(meta.get("redacted"))
        self.assertEqual(meta.get("redaction_reason"), "credentialed-terraform-module-source")
        self.assertEqual(target, "external:terraform.module:redacted-module-source")


    def test_s14_a08_terraform_escaping_local_path_rejection(self) -> None:
        """Terraform local module source path escaping repository root yields unknown target."""
        meta, target, rel = _terraform_hcl_module_source(
            "infra/environments/prod/main.tf",
            "../../../../outside_root",
        )
        self.assertEqual(rel, "module_source_local")
        self.assertEqual(target, "unknown:file:repo-escaping-terraform-module-source")
        self.assertEqual(meta.get("source_kind"), "local")
