"""Integration tests for PowerShell .psd1 and Terraform HCL CLI discovery and canonical pipeline."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from repomap_kg.canonicalization import canonicalize_observations
from repomap_kg.observations.raw import RawObservation
from repomap_test_support.cli_integration import CliIntegrationTestCase


class General1StaticContractsIntegrationTests(CliIntegrationTestCase):
    """Integration tests running real CLI subprocesses against mixed PowerShell and Terraform fixtures."""

    def test_cli_discover_mixed_powershell_and_terraform_fixtures_zero_execution(self):
        """CLI discovery extracts PowerShell manifests and Terraform HCL without running embedded snippets."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "mixed-project"
            psd1_content = """@{
    RootModule = $([System.IO.File]::WriteAllText('MARKER_PSD1', 'unexpected'); 'App.psm1')
    ModuleVersion = '1.0.0'
    Description = "$([System.IO.File]::WriteAllText('MARKER_DESCRIPTION', 'unexpected'))"
    NestedModules = @('Modules/Sub.psm1')
    RequiredModules = @('StandardModule')
    FileList = @( & { Write-Output 'dynamic-file-list' } )
    ScriptsToProcess = @('Setup.ps1')
    FunctionsToExport = @('Invoke-App')
    PrivateData = @{
        PSData = @{
            License = 'Apache-2.0'
        }
        ApiKey = 'super-secret-manifest-token-999'
    }
}"""
            psm1_content = """function Invoke-App {
    [CmdletBinding()]
    Param()
    Write-Output "Safe app execution"
}"""
            sub_psm1_content = """function Get-SubModule {
    Write-Output "Sub module"
}"""
            setup_ps1_content = """Write-Output "Setup script"
"""
            tf_content = """terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

resource "null_resource" "hostile_exec" {
  provisioner "local-exec" {
    command = "touch 'MARKER_TF'"
  }
}

module "escaping_source" {
  source = "../../../escaping_path"
}

module "cred_source" {
  source = "git::https://deployer:secret-token-pass-123@example.invalid/mod.git"
}

variable "db_password" {
  type      = string
  sensitive = true
  default   = "fake-raw-variable-secret"
}

locals {
  secret_api_token = "fake-raw-local-secret"
  safe_cluster     = "prod-cluster"
}

output "endpoint" {
  value     = "https://api.example.invalid"
  sensitive = true
}
"""
            tfvars_content = """environment = "staging"
admin_password = "fake-raw-tfvars-secret"
"""
            markers = {name: fixture / name for name in (
                "MARKER_PSD1", "MARKER_DESCRIPTION", "MARKER_TF",
            )}
            for name, marker in markers.items():
                psd1_content = psd1_content.replace(name, str(marker))
                tf_content = tf_content.replace(name, str(marker))
            self.write_fixture(fixture / "modules" / "App.psd1", psd1_content)
            self.write_fixture(fixture / "modules" / "App.psm1", psm1_content)
            self.write_fixture(fixture / "modules" / "Modules" / "Sub.psm1", sub_psm1_content)
            self.write_fixture(fixture / "modules" / "Setup.ps1", setup_ps1_content)
            self.write_fixture(fixture / "infra" / "main.tf", tf_content)
            self.write_fixture(fixture / "infra" / "terraform.tfvars", tfvars_content)

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "discover", str(fixture), "--jsonl"
            )

            # Absolute marker destinations discriminate execution regardless of child cwd.
            for marker in markers.values():
                self.assertFalse(marker.exists())

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")

        observations = [json.loads(line) for line in stdout.splitlines()]
        kinds = {o["kind"] for o in observations}
        self.assertIn("powershell.manifest", kinds)
        self.assertIn("powershell.manifest_field", kinds)
        self.assertIn("powershell.manifest_export", kinds)
        self.assertIn("powershell.manifest_dependency", kinds)
        self.assertIn("powershell.manifest_file_reference", kinds)
        self.assertIn("powershell.secret_like", kinds)
        self.assertIn("terraform.file", kinds)
        self.assertIn("terraform.block", kinds)
        self.assertIn("terraform.resource", kinds)
        self.assertIn("terraform.module", kinds)
        self.assertIn("terraform.variable", kinds)
        self.assertIn("terraform.local", kinds)
        self.assertIn("terraform.output", kinds)
        self.assertIn("terraform.redaction", kinds)

        # PowerShell manifest observations check
        ps_manifest = next(o for o in observations if o["kind"] == "powershell.manifest")
        self.assertEqual(ps_manifest["metadata"].get("file_type"), "manifest")
        self.assertTrue(ps_manifest["metadata"].get("static_only"))
        self.assertFalse(ps_manifest["metadata"].get("powershell_executed"))

        ps_fields = {
            o["name"]: o
            for o in observations
            if o["kind"] == "powershell.manifest_field"
        }
        self.assertEqual(ps_fields["RootModule"]["confidence"], "unknown")
        self.assertEqual(ps_fields["Description"]["confidence"], "unknown")
        self.assertTrue(ps_fields["ApiKey"]["metadata"].get("redacted"))

        # Terraform observations check
        tf_resource = next(o for o in observations if o["kind"] == "terraform.resource")
        self.assertTrue(tf_resource["metadata"].get("provisioner_present"))

        tf_modules = {
            o["metadata"].get("module_name"): o
            for o in observations
            if o["kind"] == "terraform.module"
        }
        self.assertEqual(
            tf_modules["escaping_source"]["target"],
            "unknown:file:repo-escaping-terraform-module-source",
        )
        self.assertTrue(tf_modules["cred_source"]["metadata"].get("redacted"))

        tf_vars = [o for o in observations if o["kind"] == "terraform.variable"]
        self.assertTrue(any(v["name"] == "db_password" and v["metadata"].get("sensitive") for v in tf_vars))
        self.assertTrue(any(v["name"] == "admin_password" and v["metadata"].get("redacted") for v in tf_vars))

        tf_locals = {
            o["name"]: o for o in observations if o["kind"] == "terraform.local"
        }
        self.assertTrue(tf_locals["secret_api_token"]["metadata"].get("redacted"))

        # Redaction verification: raw secret values must never appear in stdout
        self.assertNotIn("super-secret-manifest-token-999", stdout)
        self.assertNotIn("secret-token-pass-123", stdout)
        self.assertNotIn("fake-raw-variable-secret", stdout)
        self.assertNotIn("fake-raw-local-secret", stdout)
        self.assertNotIn("fake-raw-tfvars-secret", stdout)

    def test_cli_discover_canonical_graph_pipeline_contract(self):
        """Discovered observations from mixed fixtures successfully build canonical graphs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "canon-project"
            psd1 = """@{
    RootModule = 'Core.psm1'
    ModuleVersion = '1.0.0'
    FunctionsToExport = @('Get-ServiceStatus')
    NestedModules = @('Sub.psm1')
    RequiredModules = @('PowerShellGet')
}"""
            psm1 = """function Get-ServiceStatus {
    Write-Output "Status OK"
}"""
            sub_psm1 = """function Get-SubStatus {
    Write-Output "Sub OK"
}"""
            tf = """terraform {
  required_version = ">= 1.5.0"
}

resource "aws_s3_bucket" "data_bucket" {
  bucket = "project-data-bucket"
}

module "network" {
  source = "./modules/vpc"
}

variable "region" {
  type    = string
  default = "us-east-1"
}
"""
            self.write_fixture(fixture / "Core.psd1", psd1)
            self.write_fixture(fixture / "Core.psm1", psm1)
            self.write_fixture(fixture / "Sub.psm1", sub_psm1)
            self.write_fixture(fixture / "main.tf", tf)

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "discover", str(fixture), "--jsonl"
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")

        raw_observations = [
            RawObservation.from_dict(json.loads(line))
            for line in stdout.splitlines()
        ]
        canonical = canonicalize_observations(raw_observations, repository_scope="canon_project")
        self.assertTrue(canonical.ok)

        node_kinds = {node.kind for node in canonical.graph.nodes}
        self.assertIn("file", node_kinds)
        self.assertIn("powershell.manifest", node_kinds)
        self.assertIn("powershell.function", node_kinds)
        self.assertIn("powershell.manifest_export", node_kinds)

        self.assertTrue(len(canonical.graph.edges) >= 4)
        edge_kinds = {edge.kind for edge in canonical.graph.edges}
        self.assertIn("defines", edge_kinds)

        evidence_kinds = {ev.raw_kind for ev in canonical.graph.evidence}
        self.assertTrue(any(k.startswith("terraform.") for k in evidence_kinds))
        self.assertIn("powershell.manifest", evidence_kinds)

        self.assertTrue(len(canonical.graph.node_evidence_links) >= 1)
        self.assertTrue(len(canonical.graph.edge_evidence_links) >= 1)

    def test_cli_discover_malformed_manifest_and_hcl_boundaries_subprocesses(self):
        """CLI discover handles malformed manifests and unclosed HCL without process failure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "broken-project"
            broken_manifest = """
ModuleVersion = '1.0.0'
NestedModules = @(
    'A.psm1',
    'B.psm1'
)
CustomUnknown = & $command
"""
            broken_hcl = 'resource "aws_security_group" "broken" {\n  name = "broken-sg"\n'
            self.write_fixture(fixture / "broken.psd1", broken_manifest)
            self.write_fixture(fixture / "broken.tf", broken_hcl)

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "discover", str(fixture), "--jsonl"
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")

        observations = [json.loads(line) for line in stdout.splitlines()]
        parse_errors = [o for o in observations if o["kind"] == "terraform.parse_error"]
        self.assertTrue(len(parse_errors) >= 1)
        self.assertEqual(parse_errors[0]["metadata"].get("error_kind"), "terraform-unclosed-block")

        manifest_fields = {
            o["name"]: o for o in observations if o["kind"] == "powershell.manifest_field"
        }
        self.assertIn("ModuleVersion", manifest_fields)
        self.assertEqual(manifest_fields["ModuleVersion"]["metadata"].get("value"), "1.0.0")
        self.assertIn("NestedModules", manifest_fields)
        self.assertEqual(manifest_fields["CustomUnknown"]["confidence"], "unknown")


if __name__ == "__main__":
    sys.exit("Direct execution unsupported: use tools/run_tests.py --suite int with container sandbox admission.")
