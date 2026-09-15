import json
import subprocess
import unittest
from unittest.mock import patch

from repomap_kg.extractors.shell.powershell import extract_powershell_file_observations

from repomap_test_support.powershell import (
    POWERSHELL_FIXTURE_ROOT as FIXTURE_ROOT,
    observations_by_kind,
)


class PowerShellSideEffectExtractorUnitTests(unittest.TestCase):
    def test_extracts_file_env_and_registry_side_effect_observations(self):
        content = (FIXTURE_ROOT / "side-effects.ps1").read_text(encoding="utf-8")

        observations = extract_powershell_file_observations(
            "scripts/side-effects.ps1",
            content,
        )

        by_kind = observations_by_kind(observations)
        env_reads = {item.name: item for item in by_kind["powershell.env_read"]}
        env_writes = {item.name: item for item in by_kind["powershell.env_write"]}
        self.assertIn("EXAMPLE_HOME", env_reads)
        self.assertIn("EXAMPLE_TOKEN", env_writes)
        self.assertTrue(env_writes["EXAMPLE_TOKEN"].metadata["redacted"])

        file_reads = {
            item.metadata["target_display"]
            for item in by_kind["powershell.file_read"]
        }
        self.assertIn("./input.txt", file_reads)
        self.assertIn("./logs", file_reads)
        self.assertIn("./maybe.txt", file_reads)

        file_writes = {
            (item.metadata["operation"], item.metadata["target_kind"], item.metadata["target_display"])
            for item in by_kind["powershell.file_write"]
        }
        self.assertIn(("Set-Content", "static", "./output.txt"), file_writes)
        self.assertIn(("Add-Content", "static", "./output.txt"), file_writes)
        self.assertIn(("New-Item", "static", "./generated"), file_writes)
        self.assertIn(("Remove-Item", "static", "./old.txt"), file_writes)
        self.assertIn(("Remove-Item", "dynamic", "[dynamic]"), file_writes)
        self.assertIn(("Copy-Item", "static", "./copy.txt"), file_writes)
        self.assertIn(("Move-Item", "static", "./moved.txt"), file_writes)
        self.assertNotIn(("Remove-Item", "static", "./comment-only.txt"), file_writes)

        registry_reads = {
            item.metadata["target_display"]
            for item in by_kind["powershell.registry_read"]
        }
        registry_writes = {
            item.metadata["target_display"]
            for item in by_kind["powershell.registry_write"]
        }
        self.assertIn("HKCU:\\Software\\Example", registry_reads)
        self.assertIn("HKCU:\\Software\\Example", registry_writes)
        self.assertIn(
            "Registry::HKEY_CURRENT_USER\\Software\\Example",
            registry_writes,
        )
        self.assertNotIn("HKCU:\\Software\\StringOnly", registry_writes)

        host_categories = {
            item.metadata["mutation_category"]
            for item in by_kind["powershell.host_mutation"]
        }
        self.assertIn("file_write", host_categories)
        self.assertIn("directory_mutation", host_categories)
        self.assertIn("env_write", host_categories)
        self.assertIn("registry_write", host_categories)
        self.assertNotIn(
            "Get-Content",
            {item.metadata["operation"] for item in by_kind["powershell.host_mutation"]},
        )

    def test_extracts_network_remoting_and_operational_mutations(self):
        content = (FIXTURE_ROOT / "side-effects.ps1").read_text(encoding="utf-8")

        observations = extract_powershell_file_observations(
            "scripts/side-effects.ps1",
            content,
        )

        by_kind = observations_by_kind(observations)
        network = {item.metadata["command_name"]: item for item in by_kind["powershell.network_call"]}
        self.assertEqual(
            network["Invoke-WebRequest"].metadata["target_display"],
            "https://example.invalid/download",
        )
        self.assertEqual(
            network["Invoke-RestMethod"].metadata["method"],
            "Post",
        )
        self.assertFalse(network["Start-BitsTransfer"].metadata["network_executed"])

        remoting = {
            (item.metadata["command_name"], item.metadata["target_kind"]): item
            for item in by_kind["powershell.remoting"]
        }
        self.assertEqual(
            remoting[("Invoke-Command", "static")].metadata["target_display"],
            "example-host",
        )
        self.assertEqual(
            remoting[("Enter-PSSession", "dynamic")].metadata["target_display"],
            "[dynamic]",
        )
        self.assertFalse(remoting[("New-PSSession", "static")].metadata["remoting_executed"])

        host = by_kind["powershell.host_mutation"]
        category_operations = {
            (item.metadata["mutation_category"], item.metadata["operation"])
            for item in host
        }
        self.assertIn(("process_execution", "Start-Process"), category_operations)
        self.assertIn(("process_execution", "Stop-Process"), category_operations)
        self.assertIn(("service_control", "Start-Service"), category_operations)
        self.assertIn(("service_control", "Stop-Service"), category_operations)
        self.assertIn(("service_control", "Set-Service"), category_operations)
        self.assertIn(("service_control", "New-Service"), category_operations)
        self.assertIn(("scheduled_task", "Register-ScheduledTask"), category_operations)
        self.assertIn(("scheduled_task", "Unregister-ScheduledTask"), category_operations)
        self.assertIn(("security_policy", "Set-ExecutionPolicy"), category_operations)
        self.assertIn(("security_policy", "Set-AuthenticodeSignature"), category_operations)
        self.assertIn(("credential_handling", "Get-Credential"), category_operations)
        self.assertIn(("credential_handling", "ConvertTo-SecureString"), category_operations)
        self.assertIn(("credential_handling", "New-Object"), category_operations)

        package_mutations = [
            item for item in host if item.metadata["mutation_category"] == "package_management"
        ]
        package_tools = {
            (item.metadata["manager"], item.metadata["package_operation"])
            for item in package_mutations
        }
        self.assertIn(("PowerShellGet", "install"), package_tools)
        self.assertIn(("PowerShellGet", "update"), package_tools)
        self.assertIn(("PackageManagement", "install"), package_tools)
        self.assertIn(("winget", "install"), package_tools)
        self.assertIn(("choco", "upgrade"), package_tools)
        self.assertIn(("scoop", "uninstall"), package_tools)

    def test_side_effect_redaction_dynamic_and_non_execution_boundaries(self):
        content = (FIXTURE_ROOT / "side-effects.ps1").read_text(encoding="utf-8")

        with patch.object(subprocess, "run", side_effect=AssertionError("executed")):
            observations = extract_powershell_file_observations(
                "scripts/side-effects.ps1",
                content,
            )

        payload = "\n".join(item.to_json_line() for item in observations)
        by_kind = observations_by_kind(observations)
        self.assertNotIn("FAKE_ENV_TOKEN", payload)
        self.assertNotIn("FAKE_NET_TOKEN", payload)
        self.assertNotIn("FAKE_API_KEY", payload)
        self.assertNotIn("FAKE_PASSWORD", payload)

        self.assertNotIn(
            "$Command",
            {
                item.metadata.get("original_token")
                for item in by_kind.get("powershell.host_mutation", [])
            },
        )
        self.assertIn(
            ("Remove-Item", "dynamic", "[dynamic]"),
            {
                (
                    item.metadata["operation"],
                    item.metadata["target_kind"],
                    item.metadata["target_display"],
                )
                for item in by_kind["powershell.host_mutation"]
                if item.metadata["mutation_category"] == "file_write"
            },
        )
        self.assertTrue(
            all(
                item.metadata["powershell_executed"] is False
                for item in by_kind["powershell.host_mutation"]
            )
        )
        self.assertTrue(
            all(item.metadata["static_only"] for item in by_kind["powershell.host_mutation"])
        )

    def test_observations_are_schema_valid_json(self):
        content = (FIXTURE_ROOT / "basic-script.ps1").read_text(encoding="utf-8")

        observations = extract_powershell_file_observations(
            "scripts/basic-script.ps1",
            content,
        )

        decoded = [json.loads(item.to_json_line()) for item in observations]
        self.assertTrue(all(item["extractor"] == "repo-powershell" for item in decoded))


if __name__ == "__main__":
    unittest.main()
