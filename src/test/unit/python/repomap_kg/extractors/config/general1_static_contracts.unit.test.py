"""Unit tests for PowerShell .psd1 manifest and Terraform HCL static contract boundaries."""

import json
import unittest

from repomap_kg.extractors.config.generic import extract_config_file_observations
from repomap_kg.extractors.shell.powershell import extract_powershell_file_observations


class General1StaticContractsUnitTests(unittest.TestCase):
    """Unit tests verifying hostile, malformed, and redaction boundaries in static extractors."""

    def test_powershell_manifest_hostile_dynamic_values_never_execute_and_mark_unknown(self):
        """Dynamic expressions and command injections in manifests extract safely as unknowns."""
        manifest = """@{
    RootModule = $([System.IO.File]::WriteAllText('PWNED.txt', 'evil'))
    ModuleVersion = '1.0.0'
    Description = "prefix-$(Get-Process)-suffix"
    NestedModules = @( $env:CUSTOM_PATH + '/sub.psm1' )
    RequiredModules = @( $env:CUSTOM_MODULE )
    FileList = @( & { Start-Process malicious.exe } )
    ScriptsToProcess = @( "script`$evil.ps1" )
    FunctionsToExport = @('Get-SafeData')
}"""
        observations = extract_powershell_file_observations("modules/Hostile.psd1", manifest)
        self.assertTrue(len(observations) >= 7)
        self.assertEqual(observations[0].kind, "powershell.manifest")
        self.assertTrue(observations[0].metadata.get("static_only"))
        self.assertFalse(observations[0].metadata.get("powershell_executed"))

        fields_by_name = {
            obs.name: obs for obs in observations if obs.kind == "powershell.manifest_field"
        }
        self.assertIn("RootModule", fields_by_name)
        self.assertEqual(fields_by_name["RootModule"].confidence, "unknown")
        self.assertEqual(
            fields_by_name["RootModule"].metadata.get("unknown_reason"),
            "dynamic-variable",
        )

        self.assertIn("Description", fields_by_name)
        self.assertEqual(fields_by_name["Description"].confidence, "unknown")
        self.assertEqual(
            fields_by_name["Description"].metadata.get("unknown_reason"),
            "dynamic-string",
        )

        unknown_deps = [
            obs for obs in observations
            if obs.kind == "powershell.manifest_dependency" and obs.confidence == "unknown"
        ]
        self.assertTrue(len(unknown_deps) >= 1)
        self.assertEqual(unknown_deps[0].metadata.get("unknown_reason"), "dynamic-variable")

        unknown_refs = [
            obs for obs in observations
            if obs.kind == "powershell.manifest_file_reference" and obs.confidence == "unknown"
        ]
        self.assertTrue(len(unknown_refs) >= 1)
        self.assertEqual(unknown_refs[0].name, "[unknown]")

        for obs in observations:
            self.assertTrue(obs.metadata.get("static_only"))
            self.assertFalse(obs.metadata.get("powershell_executed"))
            if obs.start_line is not None and obs.end_line is not None:
                self.assertGreaterEqual(obs.start_line, 1)
                self.assertGreaterEqual(obs.end_line, obs.start_line)

    def test_powershell_manifest_secret_redaction_and_privatedata_boundary(self):
        """Secret-like fields and sensitive PrivateData keys are redacted and omitted from payload."""
        manifest = """@{
    RootModule = 'Safe.psm1'
    ModuleVersion = '2.1.0'
    ApiKey = 'sensitive-manifest-token-12345'
    SecretKey = 'top-secret-signing-key-67890'
    Password = 'hunter2-super-secret-password'
    PrivateData = @{
        PSData = @{
            Tags = @('safe-tag')
            ProjectUri = 'https://example.com'
        }
        Token = 'bearer-token-in-privatedata'
        SafeSetting = 'unredacted-safe-value'
    }
}"""
        observations = extract_powershell_file_observations("modules/Secret.psd1", manifest)
        payload = json.dumps([o.to_dict() for o in observations], sort_keys=True)

        secret_likes = [o for o in observations if o.kind == "powershell.secret_like"]
        secret_names = {s.name for s in secret_likes}
        self.assertIn("ApiKey", secret_names)
        self.assertIn("SecretKey", secret_names)
        self.assertIn("Password", secret_names)
        self.assertIn("PrivateData.Token", secret_names)

        fields = {
            o.metadata.get("field_path"): o
            for o in observations
            if o.kind == "powershell.manifest_field"
        }
        self.assertTrue(fields["ApiKey"].metadata.get("redacted"))
        self.assertEqual(fields["ApiKey"].metadata.get("value"), "[redacted]")
        self.assertFalse(fields["ApiKey"].metadata.get("raw_value_stored"))
        self.assertTrue(fields["PrivateData.Token"].metadata.get("redacted"))

        private_data_obs = [
            o for o in observations if o.kind == "powershell.manifest_private_data"
        ]
        pd_names = {pd.name for pd in private_data_obs}
        self.assertIn("PrivateData.SafeSetting", pd_names)
        self.assertNotIn("PrivateData.Token", pd_names)

        self.assertNotIn("sensitive-manifest-token-12345", payload)
        self.assertNotIn("top-secret-signing-key-67890", payload)
        self.assertNotIn("hunter2-super-secret-password", payload)
        self.assertNotIn("bearer-token-in-privatedata", payload)

    def test_powershell_manifest_lexical_branches_and_legacy_fallback(self):
        """Escaped quotes, typed literals, path traversal escape, and fallback parser behavior."""
        manifest = """@{
    ModuleVersion = '3.0.0'
    Description = 'Developer''s ''Special'' Manifest'
    RequireLicenseAcceptance = $true
    ClrVersion = 4
    DefaultCommandPrefix = $null
    FunctionsToExport = @('*')
    AliasesToExport = @('my-alias')
    NestedModules = @('../../escape.psm1', './local.psm1')
    FileList = @('data.txt')
}"""
        observations = extract_powershell_file_observations("modules/Lexical.psd1", manifest)
        fields = {
            o.name: o for o in observations if o.kind == "powershell.manifest_field"
        }
        self.assertEqual(fields["Description"].metadata.get("value"), "Developer's 'Special' Manifest")
        self.assertEqual(fields["RequireLicenseAcceptance"].metadata.get("value"), True)
        self.assertEqual(fields["ClrVersion"].metadata.get("value"), 4)
        self.assertIsNone(fields["DefaultCommandPrefix"].metadata.get("value"))

        exports = [o for o in observations if o.kind == "powershell.manifest_export"]
        wildcards = [e for e in exports if e.metadata.get("wildcard") is True]
        self.assertEqual(len(wildcards), 1)
        self.assertEqual(wildcards[0].target, "powershell-export:function:*")

        file_refs = {
            o.name: o for o in observations if o.kind == "powershell.manifest_file_reference"
        }
        self.assertIn("../../escape.psm1", file_refs)
        self.assertEqual(file_refs["../../escape.psm1"].metadata.get("resolution"), "module-name")
        self.assertIsNone(file_refs["../../escape.psm1"].target)

        self.assertIn("./local.psm1", file_refs)
        self.assertEqual(file_refs["./local.psm1"].metadata.get("resolution"), "static")
        self.assertEqual(file_refs["./local.psm1"].target, "file:modules/local.psm1")

        fallback_manifest = """
ModuleVersion = '1.0.0'
NestedModules = @(
    'A.psm1',
    'B.psm1'
)
CustomUnsupported = & $script
"""
        fallback_obs = extract_powershell_file_observations("modules/Fallback.psd1", fallback_manifest)
        fallback_fields = {
            o.name: o for o in fallback_obs if o.kind == "powershell.manifest_field"
        }
        self.assertIn("ModuleVersion", fallback_fields)
        self.assertEqual(fallback_fields["ModuleVersion"].metadata.get("value"), "1.0.0")
        self.assertIn("NestedModules", fallback_fields)
        self.assertEqual(fallback_fields["NestedModules"].metadata.get("values"), ["A.psm1", "B.psm1"])
        self.assertIn("CustomUnsupported", fallback_fields)
        self.assertEqual(fallback_fields["CustomUnsupported"].confidence, "unknown")

    def test_terraform_hcl_module_source_escaping_and_credential_redaction(self):
        """Relative escaping paths and credentialed URLs in module sources are safe and redacted."""
        hcl = """
module "escaping_relative" {
  source = "../../../outside/repo"
}

module "credentialed_git" {
  source = "git::https://deploy-user:deploy-pass-secret@git.example.invalid/mod.git"
}

module "dynamic_source" {
  source = var.dynamic_module_url
}
"""
        observations = extract_config_file_observations("infra/modules.tf", hcl)
        payload = json.dumps([o.to_dict() for o in observations], sort_keys=True)

        observed_modules = {
            o.metadata.get("module_name"): o
            for o in observations
            if o.kind == "terraform.module"
        }
        self.assertEqual(
            observed_modules["escaping_relative"].target,
            "unknown:file:repo-escaping-terraform-module-source",
        )

        cred = observed_modules["credentialed_git"]
        self.assertTrue(cred.metadata.get("redacted"))
        self.assertEqual(
            cred.target,
            "external:terraform.module:redacted-module-source",
        )

        dyn = observed_modules["dynamic_source"]
        self.assertTrue(dyn.metadata.get("dynamic"))
        self.assertTrue(dyn.metadata.get("not_fetched"))
        self.assertEqual(dyn.metadata.get("source_expression_kind"), "traversal_reference")

        self.assertNotIn("deploy-pass-secret", payload)

    def test_terraform_hcl_secrets_redaction_in_attributes_locals_and_import(self):
        """Secret-like attributes, credentialed URLs in attributes, locals, and import IDs are redacted."""
        hcl = """
resource "aws_db_instance" "database" {
  password = "db-password-super-secret-123"
  auth_token = "auth-token-sensitive-xyz"
  endpoint_url = "https://admin:pass-in-url@db.example.invalid:5432"
}

locals {
  client_secret = "raw-local-secret-token"
  safe_variable = "unredacted-public-name"
}

import {
  to = aws_s3_bucket.imported
  id = "secret-import-identifier-999"
}
"""
        observations = extract_config_file_observations("infra/secrets.tf", hcl)
        payload = json.dumps([o.to_dict() for o in observations], sort_keys=True)

        redactions = [o for o in observations if o.kind == "terraform.redaction"]
        redaction_fields = {r.metadata.get("field_name") for r in redactions}
        self.assertIn("password", redaction_fields)
        self.assertIn("auth_token", redaction_fields)
        self.assertIn("endpoint_url", redaction_fields)
        self.assertIn("client_secret", redaction_fields)
        self.assertIn("id", redaction_fields)

        locals_by_name = {
            o.name: o for o in observations if o.kind == "terraform.local"
        }
        self.assertTrue(locals_by_name["client_secret"].metadata.get("redacted"))
        self.assertEqual(locals_by_name["client_secret"].metadata.get("expression_kind"), "redacted")
        self.assertFalse(locals_by_name["safe_variable"].metadata.get("redacted"))

        imports = [o for o in observations if o.kind == "terraform.import"]
        self.assertEqual(len(imports), 1)
        self.assertTrue(imports[0].metadata.get("id_redacted"))
        self.assertTrue(imports[0].metadata.get("redacted"))

        self.assertNotIn("db-password-super-secret-123", payload)
        self.assertNotIn("auth-token-sensitive-xyz", payload)
        self.assertNotIn("pass-in-url", payload)
        self.assertNotIn("raw-local-secret-token", payload)
        self.assertNotIn("secret-import-identifier-999", payload)

    def test_terraform_hcl_parse_errors_limits_and_diagnostics(self):
        """Unclosed blocks and byte limits emit conservative parse errors without crashing."""
        unclosed_hcl = 'resource "aws_vpc" "broken" {\n  cidr_block = "10.0.0.0/16"\n'
        observations = extract_config_file_observations("infra/broken.tf", unclosed_hcl)
        parse_errors = [o for o in observations if o.kind == "terraform.parse_error"]
        self.assertTrue(len(parse_errors) >= 1)
        self.assertEqual(parse_errors[0].metadata.get("error_kind"), "terraform-unclosed-block")
        self.assertTrue(parse_errors[0].metadata.get("recovered"))
        self.assertEqual(parse_errors[0].start_line, 1)

        huge_hcl = "# " + ("x" * (1024 * 1024 + 200))
        huge_obs = extract_config_file_observations("infra/huge.tf", huge_hcl)
        huge_errors = [o for o in huge_obs if o.kind == "terraform.parse_error"]
        self.assertTrue(len(huge_errors) >= 1)
        self.assertEqual(huge_errors[0].metadata.get("error_kind"), "terraform-file-byte-limit")
        self.assertFalse(huge_errors[0].metadata.get("recovered"))

        advanced_hcl = """
check "endpoint_health" {
  assert {
    condition = true
    error_message = "health check failed"
  }
}

moved {
  from = aws_instance.old_instance
  to = aws_instance.new_instance
}

removed {
  from = aws_instance.retired_instance
}
"""
        advanced_obs = extract_config_file_observations("infra/advanced.tf", advanced_hcl)
        checks = [o for o in advanced_obs if o.kind == "terraform.check"]
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].metadata.get("assertion_count"), 1)

        moved = [o for o in advanced_obs if o.kind == "terraform.moved"]
        self.assertEqual(len(moved), 1)
        self.assertEqual(moved[0].metadata.get("from_summary"), "aws_instance.old_instance")
        self.assertEqual(moved[0].metadata.get("to_summary"), "aws_instance.new_instance")

        removed = [o for o in advanced_obs if o.kind == "terraform.removed"]
        self.assertEqual(len(removed), 1)
        self.assertEqual(removed[0].metadata.get("from_summary"), "aws_instance.retired_instance")

    def test_terraform_tfvars_hcl_hostile_and_all_values_redacted(self):
        """All tfvars attributes are marked sensitive and redacted by default regardless of shape."""
        tfvars = """
db_password = "super-sensitive-master-pass"
api_keys = ["key-1", "key-2"]
nested_config = {
  internal_secret = "raw-nested-secret"
}
node_count = 5
is_production = true
"""
        observations = extract_config_file_observations("prod.auto.tfvars", tfvars)
        payload = json.dumps([o.to_dict() for o in observations], sort_keys=True)

        file_obs = next(o for o in observations if o.kind == "terraform.file")
        self.assertEqual(file_obs.metadata.get("file_family"), "tfvars")
        self.assertTrue(file_obs.metadata.get("all_values_sensitive"))

        variables = [o for o in observations if o.kind == "terraform.variable"]
        self.assertEqual(len(variables), 5)
        for var in variables:
            self.assertTrue(var.metadata.get("redacted"))
            self.assertEqual(var.metadata.get("redaction_reason"), "tfvars-sensitive-by-default")

        redactions = [o for o in observations if o.kind == "terraform.redaction"]
        self.assertEqual(len(redactions), 5)

        self.assertNotIn("super-sensitive-master-pass", payload)
        self.assertNotIn("key-1", payload)
        self.assertNotIn("raw-nested-secret", payload)
