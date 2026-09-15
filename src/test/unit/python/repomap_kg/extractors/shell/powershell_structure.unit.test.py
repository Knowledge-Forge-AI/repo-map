import subprocess
import unittest
from unittest.mock import patch

from repomap_kg.extractors.shell.powershell import extract_powershell_file_observations

from repomap_test_support.powershell import (
    POWERSHELL_FIXTURE_ROOT as FIXTURE_ROOT,
    observations_by_kind,
)


class PowerShellStructureExtractorUnitTests(unittest.TestCase):
    def test_extracts_script_structure_requires_imports_dot_source_and_params(self):
        content = (FIXTURE_ROOT / "basic-script.ps1").read_text(encoding="utf-8")

        observations = extract_powershell_file_observations(
            "scripts/basic-script.ps1",
            content,
        )

        by_kind = observations_by_kind(observations)
        self.assertEqual(by_kind["powershell.script"][0].path, "scripts/basic-script.ps1")
        self.assertEqual(by_kind["powershell.script"][0].confidence, "extracted")
        self.assertEqual(by_kind["powershell.script"][0].metadata["file_type"], "script")
        self.assertEqual(by_kind["powershell.requires"][0].name, "Version")
        self.assertEqual(by_kind["powershell.requires"][0].metadata["value"], "7.2")
        self.assertEqual(
            by_kind["powershell.using_module"][0].target,
            "file:scripts/Example.Module.psm1",
        )
        self.assertEqual(
            by_kind["powershell.import_module"][0].target,
            "module:Microsoft.PowerShell.Management",
        )
        self.assertEqual(
            by_kind["powershell.dot_source"][0].target,
            "file:scripts/helpers/Example.Shared.ps1",
        )
        self.assertEqual(
            [item.name for item in by_kind["powershell.function"]],
            ["Invoke-ExampleMaintenance"],
        )
        params = {(item.name, item.metadata["scope"]) for item in by_kind["powershell.param"]}
        self.assertIn(("Path", "file"), params)
        self.assertIn(("ApiToken", "file"), params)
        self.assertIn(("OutputDirectory", "function"), params)
        self.assertNotIn(("true", "function"), params)

    def test_extracts_module_file_and_scoped_function_names(self):
        content = (FIXTURE_ROOT / "Example.Module.psm1").read_text(encoding="utf-8")

        observations = extract_powershell_file_observations(
            "modules/Example.Module.psm1",
            content,
        )

        by_kind = observations_by_kind(observations)
        self.assertEqual(by_kind["powershell.module"][0].metadata["file_type"], "module")
        self.assertEqual(
            [item.name for item in by_kind["powershell.function"]],
            ["Get-ExampleReport", "Invoke-ScopedThing"],
        )
        self.assertEqual(
            by_kind["powershell.function"][1].metadata["scope_prefix"],
            "script",
        )
        local_param = next(
            item for item in by_kind["powershell.param"] if item.name == "Name"
        )
        self.assertEqual(local_param.metadata["function"], "Invoke-ScopedThing")

    def test_one_line_function_does_not_capture_later_file_param_block(self):
        observations = extract_powershell_file_observations(
            "scripts/scope.ps1",
            (
                "function Invoke-Thing { param([string]$Name) }\n"
                "param([string]$Later)\n"
            ),
        )

        params = [
            (item.name, item.metadata["scope"], item.metadata.get("function"))
            for item in observations
            if item.kind == "powershell.param"
        ]

        self.assertEqual(
            params,
            [
                ("Name", "function", "Invoke-Thing"),
                ("Later", "file", None),
            ],
        )

    def test_extracts_manifest_file_without_evaluating_expressions(self):
        content = (FIXTURE_ROOT / "Example.Module.psd1").read_text(encoding="utf-8")

        observations = extract_powershell_file_observations(
            "modules/Example.Module.psd1",
            content,
        )

        by_kind = observations_by_kind(observations)
        manifest = by_kind["powershell.manifest"][0]
        self.assertEqual(manifest.confidence, "extracted")
        self.assertEqual(manifest.metadata["file_type"], "manifest")
        fields = {item.name: item for item in by_kind["powershell.manifest_field"]}
        self.assertEqual(fields["RootModule"].metadata["value"], "Example.Module.psm1")
        self.assertEqual(fields["ModuleVersion"].metadata["value"], "0.1.0")
        self.assertEqual(fields["FunctionsToExport"].metadata["values"], [
            "Get-ExampleReport",
            "Invoke-ScopedThing",
        ])
        self.assertEqual(fields["PrivateData"].confidence, "unknown")
        self.assertEqual(fields["PrivateData"].metadata["resolution"], "unknown")

    def test_extracts_literal_manifest_fields_and_private_data(self):
        content = (FIXTURE_ROOT / "Advanced.Module.psd1").read_text(encoding="utf-8")

        observations = extract_powershell_file_observations(
            "modules/Advanced.Module.psd1",
            content,
        )

        by_kind = observations_by_kind(observations)
        fields = {
            item.metadata["field_path"]: item
            for item in by_kind["powershell.manifest_field"]
        }
        self.assertEqual(fields["RootModule"].metadata["value"], "Advanced.Module.psm1")
        self.assertEqual(fields["ModuleVersion"].metadata["value"], "1.2.3")
        self.assertEqual(fields["GUID"].metadata["value"], "11111111-2222-3333-4444-555555555555")
        self.assertEqual(
            fields["CompatiblePSEditions"].metadata["values"],
            ["Core", "Desktop"],
        )
        self.assertEqual(fields["IsPreview"].metadata["value"], True)
        self.assertEqual(fields["IsPreview"].metadata["value_type"], "bool")
        self.assertEqual(fields["Count"].metadata["value"], 42)
        self.assertEqual(fields["Count"].metadata["value_type"], "int")
        self.assertIsNone(fields["OptionalValue"].metadata["value"])
        self.assertEqual(fields["OptionalValue"].metadata["value_type"], "null")

        private_data = {
            item.metadata["field_path"]: item
            for item in by_kind["powershell.manifest_private_data"]
        }
        self.assertEqual(
            private_data["PrivateData.PSData.Tags"].metadata["values"],
            ["repomap", "static-fixture"],
        )
        self.assertEqual(
            private_data["PrivateData.PSData.ProjectUri"].metadata["value"],
            "https://example.invalid/project",
        )
        self.assertEqual(
            private_data["PrivateData.PSData.Prerelease"].metadata["value"],
            "alpha",
        )

    def test_extracts_manifest_dependencies_file_references_and_exports(self):
        content = (FIXTURE_ROOT / "Advanced.Module.psd1").read_text(encoding="utf-8")

        observations = extract_powershell_file_observations(
            "modules/Advanced.Module.psd1",
            content,
        )

        by_kind = observations_by_kind(observations)
        dependencies = {
            (
                item.metadata["field"],
                item.metadata["dependency_kind"],
                item.metadata.get("module_name") or item.metadata.get("assembly_name"),
            ): item
            for item in by_kind["powershell.manifest_dependency"]
        }
        self.assertIn(("RequiredModules", "module", "ThreadJob"), dependencies)
        self.assertEqual(
            dependencies[("RequiredModules", "module", "Pester")].metadata["module_version"],
            "5.0.0",
        )
        self.assertEqual(
            dependencies[("RequiredModules", "module", "ThreadJob")].metadata["required_version"],
            "2.0.3",
        )
        self.assertIn(("RequiredAssemblies", "assembly", "System.Text.Json"), dependencies)
        self.assertIn(("NestedModules", "nested_module", "Nested.Module.psm1"), dependencies)

        references = {
            (item.metadata["field"], item.metadata["reference"]): item
            for item in by_kind["powershell.manifest_file_reference"]
        }
        self.assertEqual(
            references[("RootModule", "Advanced.Module.psm1")].metadata["resolved_path"],
            "modules/Advanced.Module.psm1",
        )
        self.assertEqual(
            references[("ScriptsToProcess", "scripts/init.ps1")].metadata["resolved_path"],
            "modules/scripts/init.ps1",
        )
        self.assertEqual(
            references[("TypesToProcess", "types/Advanced.Types.ps1xml")].metadata["resolved_path"],
            "modules/types/Advanced.Types.ps1xml",
        )
        self.assertEqual(
            references[("FormatsToProcess", "formats/Advanced.Format.ps1xml")].metadata["resolved_path"],
            "modules/formats/Advanced.Format.ps1xml",
        )
        self.assertEqual(
            references[("FileList", "README.md")].metadata["resolved_path"],
            "modules/README.md",
        )

        exports = {
            (item.metadata["export_kind"], item.name, item.metadata["wildcard"])
            for item in by_kind["powershell.manifest_export"]
        }
        self.assertIn(("function", "Get-AdvancedThing", False), exports)
        self.assertIn(("function", "Invoke-AdvancedThing", False), exports)
        self.assertIn(("alias", "*", True), exports)
        self.assertIn(("variable", "AdvancedConfig", False), exports)
        self.assertIn(("dsc_resource", "AdvancedResource", False), exports)
        self.assertNotIn(("function", "CommentedOut", False), exports)

    def test_manifest_unknowns_and_secret_values_are_bounded_and_redacted(self):
        content = (FIXTURE_ROOT / "Advanced.Module.psd1").read_text(encoding="utf-8")

        with patch.object(subprocess, "run", side_effect=AssertionError("executed")):
            observations = extract_powershell_file_observations(
                "modules/Advanced.Module.psd1",
                content,
            )

        payload = "\n".join(item.to_json_line() for item in observations)
        by_kind = observations_by_kind(observations)
        fields = {
            item.metadata["field_path"]: item
            for item in by_kind["powershell.manifest_field"]
        }
        self.assertEqual(fields["GeneratedOn"].confidence, "unknown")
        self.assertEqual(fields["GeneratedOn"].metadata["resolution"], "unknown")
        self.assertEqual(fields["DynamicVersion"].confidence, "unknown")
        self.assertEqual(fields["DynamicVersion"].metadata["unknown_reason"], "dynamic-variable")

        secret_like = [
            item for item in by_kind["powershell.secret_like"]
            if item.metadata["secret_source"] == "manifest_field"
        ]
        self.assertEqual(
            {item.name for item in secret_like},
            {
                "PrivateData.ApiToken",
                "PrivateData.ApiKey",
                "PrivateData.Password",
                "PrivateData.PatValue",
                "PrivateData.Authorization",
            },
        )
        self.assertTrue(all(item.metadata["redacted"] for item in secret_like))
        self.assertNotIn("FAKE_MANIFEST_TOKEN", payload)
        self.assertNotIn("FAKE_MANIFEST_API_KEY", payload)
        self.assertNotIn("FAKE_MANIFEST_PASSWORD", payload)
        self.assertNotIn("fake-manifest-pat", payload)
        self.assertNotIn("Bearer FAKE_MANIFEST_AUTH", payload)

    def test_dynamic_invocation_and_dynamic_dot_source_are_bounded_unknowns(self):
        content = (FIXTURE_ROOT / "dynamic-and-secrets.ps1").read_text(encoding="utf-8")

        observations = extract_powershell_file_observations(
            "scripts/dynamic-and-secrets.ps1",
            content,
        )

        dynamic = [
            item for item in observations if item.kind == "powershell.dynamic_invocation"
        ]
        self.assertEqual(
            [(item.name, item.confidence, item.metadata["resolution"]) for item in dynamic],
            [
                ("dot-source", "unknown", "dynamic"),
                ("call-operator", "unknown", "dynamic"),
                ("Invoke-Expression", "unknown", "dynamic"),
            ],
        )
        self.assertTrue(all(item.target is None for item in dynamic))

    def test_secret_like_parameters_and_values_are_redacted_from_payloads(self):
        content = (FIXTURE_ROOT / "dynamic-and-secrets.ps1").read_text(encoding="utf-8")

        observations = extract_powershell_file_observations(
            "scripts/dynamic-and-secrets.ps1",
            content,
        )

        payload = "\n".join(item.to_json_line() for item in observations)
        secret_like = [
            item for item in observations if item.kind == "powershell.secret_like"
        ]
        param = next(item for item in observations if item.kind == "powershell.param")
        self.assertTrue(param.metadata["redacted"])
        self.assertEqual(param.metadata["redaction_reason"], "secret-like parameter name")
        self.assertEqual(
            {(item.name, item.metadata["secret_source"]) for item in secret_like},
            {
                ("ApiToken", "parameter"),
                ("Authorization", "assignment"),
                ("PatValue", "assignment"),
            },
        )
        self.assertTrue(all(item.metadata["redacted"] for item in secret_like))
        self.assertNotIn("FAKE_TOKEN_VALUE", payload)
        self.assertNotIn("Bearer EXAMPLE_SHOULD_NOT_LEAK", payload)
        self.assertNotIn("fake-pat-value", payload)

    def test_extractor_does_not_call_subprocess_or_powershell(self):
        content = (FIXTURE_ROOT / "basic-script.ps1").read_text(encoding="utf-8")

        with patch.object(subprocess, "run", side_effect=AssertionError("executed")):
            observations = extract_powershell_file_observations(
                "scripts/basic-script.ps1",
                content,
            )

        self.assertIn("powershell.script", {item.kind for item in observations})


if __name__ == "__main__":
    unittest.main()
