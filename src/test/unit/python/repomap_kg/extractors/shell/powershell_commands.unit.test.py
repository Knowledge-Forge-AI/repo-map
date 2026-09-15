import subprocess
import unittest
from unittest.mock import patch

from repomap_kg.extractors.shell.powershell import extract_powershell_file_observations

from repomap_test_support.powershell import (
    POWERSHELL_FIXTURE_ROOT as FIXTURE_ROOT,
    observations_by_kind,
)


class PowerShellCommandExtractorUnitTests(unittest.TestCase):
    def test_extracts_static_commands_aliases_arguments_splats_and_pipeline_order(self):
        content = (FIXTURE_ROOT / "commands-and-pipelines.ps1").read_text(
            encoding="utf-8"
        )

        observations = extract_powershell_file_observations(
            "scripts/commands-and-pipelines.ps1",
            content,
        )

        by_kind = observations_by_kind(observations)
        commands = {item.name: item for item in by_kind["powershell.command"]}
        self.assertIn("Get-ChildItem", commands)
        self.assertIn("Where-Object", commands)
        self.assertIn("ForEach-Object", commands)
        self.assertIn("Invoke-RestMethod", commands)
        self.assertNotIn("Remove-Item", commands)
        self.assertNotIn("Copy-Item", commands)
        self.assertNotIn(
            ("file_write", "Remove-Item"),
            {
                (item.metadata["mutation_category"], item.metadata["operation"])
                for item in by_kind.get("powershell.host_mutation", [])
            },
        )

        pipeline = by_kind["powershell.pipeline"][0]
        self.assertEqual(pipeline.metadata["segment_count"], 3)
        pipeline_id = pipeline.metadata["pipeline_id"]
        pipeline_commands = [
            item
            for item in by_kind["powershell.command"]
            if item.metadata.get("pipeline_id") == pipeline_id
        ]
        self.assertEqual(
            [(item.name, item.metadata["pipeline_index"]) for item in pipeline_commands],
            [
                ("Get-ChildItem", 0),
                ("Where-Object", 1),
                ("ForEach-Object", 2),
            ],
        )
        self.assertTrue(
            all(item.metadata["static_only"] for item in by_kind["powershell.command"])
        )
        self.assertTrue(
            all(
                item.metadata["powershell_executed"] is False
                for item in by_kind["powershell.command"]
            )
        )

        aliases = {item.name: item for item in by_kind["powershell.alias_command"]}
        self.assertEqual(aliases["gci"].metadata["normalized_command"], "Get-ChildItem")
        self.assertEqual(aliases["cat"].metadata["normalized_command"], "Get-Content")
        alias_commands = [
            item
            for item in by_kind["powershell.command"]
            if item.metadata.get("alias_expansion")
        ]
        self.assertEqual(
            {(item.metadata["original_token"], item.name) for item in alias_commands},
            {("gci", "Get-ChildItem"), ("cat", "Get-Content")},
        )

        splats = by_kind["powershell.splat"]
        self.assertEqual([(item.name, item.metadata["command_name"]) for item in splats], [
            ("Params", "Get-ChildItem"),
        ])

        arguments = by_kind["powershell.command_argument"]
        named_args = {
            (item.metadata["command_name"], item.metadata["argument_name"]): item
            for item in arguments
            if "argument_name" in item.metadata
        }
        self.assertEqual(
            named_args[("Get-ChildItem", "Path")].metadata["value_kind"],
            "dynamic",
        )
        self.assertEqual(
            named_args[("Get-ChildItem", "Filter")].metadata["value"],
            "*.json",
        )
        self.assertEqual(
            named_args[("Get-ChildItem", "Force")].metadata["value_kind"],
            "switch",
        )
        self.assertTrue(named_args[("Invoke-RestMethod", "ApiKey")].metadata["redacted"])

        positional_values = {
            (
                item.metadata["command_name"],
                item.metadata["argument_position"],
                item.metadata.get("value"),
            )
            for item in arguments
            if "argument_position" in item.metadata
        }
        self.assertIn(("Get-Content", 0, "./README.md"), positional_values)

    def test_extracts_external_commands_without_executing_them(self):
        content = (FIXTURE_ROOT / "commands-and-pipelines.ps1").read_text(
            encoding="utf-8"
        )

        observations = extract_powershell_file_observations(
            "scripts/commands-and-pipelines.ps1",
            content,
        )

        by_kind = observations_by_kind(observations)
        external = {item.name: item for item in by_kind["powershell.external_command"]}
        self.assertEqual(
            set(external),
            {
                "git",
                "docker",
                "kubectl",
                "terraform",
                "winget",
                "choco",
                "scoop",
                "npm",
                "python",
                "pwsh",
            },
        )
        self.assertEqual(external["pwsh"].target, "tool:pwsh")
        self.assertTrue(
            all(item.metadata["powershell_executed"] is False for item in external.values())
        )
        self.assertTrue(all(item.metadata["static_only"] for item in external.values()))

    def test_command_secrets_are_redacted_and_dynamic_commands_stay_bounded(self):
        content = (FIXTURE_ROOT / "commands-and-pipelines.ps1").read_text(
            encoding="utf-8"
        )

        observations = extract_powershell_file_observations(
            "scripts/commands-and-pipelines.ps1",
            content,
        )

        payload = "\n".join(item.to_json_line() for item in observations)
        by_kind = observations_by_kind(observations)
        dynamic = [
            item for item in by_kind["powershell.dynamic_invocation"] if item.name == "call-operator"
        ]
        self.assertEqual(len(dynamic), 1)
        self.assertNotIn("$Command", {
            item.metadata.get("original_token") for item in by_kind.get("powershell.command", [])
        })
        self.assertNotIn(
            "$Command",
            {item.metadata.get("original_token") for item in by_kind.get("powershell.external_command", [])},
        )
        secret_like = [
            item
            for item in by_kind["powershell.secret_like"]
            if item.metadata["secret_source"] in {"command_argument", "command_hashtable"}
        ]
        self.assertEqual(
            {(item.name, item.metadata["secret_source"]) for item in secret_like},
            {
                ("Authorization", "command_hashtable"),
                ("ApiKey", "command_argument"),
            },
        )
        self.assertNotIn("FAKE_ARG_SECRET", payload)
        self.assertNotIn("FAKE_INLINE_SECRET", payload)
        self.assertNotIn("FAKE_PIPELINE_SECRET", payload)

    def test_alias_definitions_builtin_aliases_and_local_alias_use_are_bounded(self):
        content = (FIXTURE_ROOT / "aliases-splats-dynamic.ps1").read_text(
            encoding="utf-8"
        )

        observations = extract_powershell_file_observations(
            "scripts/aliases-splats-dynamic.ps1",
            content,
        )

        by_kind = observations_by_kind(observations)
        definitions = {
            item.metadata["alias_name"]: item
            for item in by_kind["powershell.alias_definition"]
        }
        self.assertEqual(definitions["ll"].metadata["target_name"], "Get-ChildItem")
        self.assertEqual(definitions["ll"].metadata["target_family"], "cmdlet")
        self.assertEqual(definitions["k"].metadata["target_name"], "kubectl")
        self.assertEqual(definitions["k"].metadata["target_family"], "external")
        self.assertTrue(
            all(
                item.metadata["powershell_executed"] is False
                for item in by_kind["powershell.alias_definition"]
            )
        )

        aliases = {item.name: item for item in by_kind["powershell.alias_command"]}
        self.assertEqual(aliases["ll"].metadata["normalized_command"], "Get-ChildItem")
        self.assertEqual(aliases["ll"].metadata["alias_source"], "local")
        self.assertEqual(aliases["echo"].metadata["normalized_command"], "Write-Output")
        self.assertEqual(aliases["curl"].metadata["normalized_command"], "Invoke-WebRequest")
        self.assertEqual(aliases["wget"].metadata["normalized_command"], "Invoke-WebRequest")
        self.assertEqual(aliases["mkdir"].metadata["normalized_command"], "New-Item")
        self.assertEqual(aliases["rmdir"].metadata["normalized_command"], "Remove-Item")

        commands = {
            (item.metadata["original_token"], item.name)
            for item in by_kind["powershell.command"]
        }
        self.assertIn(("ll", "Get-ChildItem"), commands)
        self.assertIn(("echo", "Write-Output"), commands)
        self.assertIn(("curl", "Invoke-WebRequest"), commands)
        self.assertIn(("wget", "Invoke-WebRequest"), commands)

    def test_splat_assignments_are_summarized_and_linked_without_secret_leaks(self):
        content = (FIXTURE_ROOT / "aliases-splats-dynamic.ps1").read_text(
            encoding="utf-8"
        )

        observations = extract_powershell_file_observations(
            "scripts/aliases-splats-dynamic.ps1",
            content,
        )

        payload = "\n".join(item.to_json_line() for item in observations)
        by_kind = observations_by_kind(observations)
        assignment = by_kind["powershell.splat_assignment"][0]
        self.assertEqual(assignment.name, "Params")
        self.assertEqual(assignment.metadata["key_count"], 6)
        self.assertEqual(
            assignment.metadata["known_keys"],
            ["Path", "Filter", "Force", "Count", "DynamicPath"],
        )
        self.assertEqual(assignment.metadata["redacted_keys"], ["ApiToken"])
        self.assertTrue(assignment.metadata["contains_dynamic_values"])
        self.assertFalse(assignment.metadata["expansion_modeled"])

        splat = by_kind["powershell.splat"][0]
        self.assertEqual(splat.name, "Params")
        self.assertEqual(splat.metadata["command_name"], "Get-ChildItem")
        self.assertEqual(splat.metadata["assignment_source_id"], assignment.source_id)
        self.assertEqual(
            splat.metadata["known_keys"],
            ["Path", "Filter", "Force", "Count", "DynamicPath"],
        )
        self.assertEqual(splat.metadata["redacted_keys"], ["ApiToken"])

        secret_like = [
            item
            for item in by_kind["powershell.secret_like"]
            if item.metadata["secret_source"] == "splat_assignment"
        ]
        self.assertEqual({item.name for item in secret_like}, {"Params.ApiToken"})
        self.assertNotIn("FAKE_SPLAT_TOKEN", payload)

    def test_dynamic_invocation_static_targets_are_bounded_without_execution(self):
        content = (FIXTURE_ROOT / "aliases-splats-dynamic.ps1").read_text(
            encoding="utf-8"
        )

        observations = extract_powershell_file_observations(
            "scripts/aliases-splats-dynamic.ps1",
            content,
        )

        dynamic = [
            item for item in observations if item.kind == "powershell.dynamic_invocation"
        ]
        records = {
            (item.name, item.metadata["target_kind"], item.metadata["dynamic_reason"])
            for item in dynamic
        }
        self.assertIn(("call-operator", "dynamic", "call-operator-dynamic-target"), records)
        self.assertIn(("call-operator", "static", "call-operator-static-target"), records)
        self.assertIn(("Invoke-Expression", "dynamic", "invoke-expression"), records)
        self.assertIn(("dot-source", "dynamic", "dynamic-dot-source-target"), records)

        static_targets = {
            item.metadata["target_display"]
            for item in dynamic
            if item.metadata["target_kind"] == "static"
        }
        self.assertIn("git", static_targets)
        self.assertIn("./scripts/run.ps1", static_targets)
        self.assertTrue(all(item.metadata["powershell_executed"] is False for item in dynamic))
        self.assertTrue(all(item.metadata["static_only"] for item in dynamic))

    def test_comments_here_strings_assignments_and_hashtable_entries_are_not_commands(self):
        content = (FIXTURE_ROOT / "aliases-splats-dynamic.ps1").read_text(
            encoding="utf-8"
        )

        with patch.object(subprocess, "run", side_effect=AssertionError("executed")):
            observations = extract_powershell_file_observations(
                "scripts/aliases-splats-dynamic.ps1",
                content,
            )

        by_kind = observations_by_kind(observations)
        command_tokens = {
            item.metadata.get("original_token")
            for item in by_kind.get("powershell.command", [])
        }
        external_tokens = {
            item.metadata.get("original_token")
            for item in by_kind.get("powershell.external_command", [])
        }
        host_targets = {
            item.metadata.get("target_display")
            for item in by_kind.get("powershell.host_mutation", [])
        }
        network_targets = {
            item.metadata.get("target_display")
            for item in by_kind.get("powershell.network_call", [])
        }

        self.assertNotIn("Set-ItemProperty", command_tokens)
        self.assertNotIn("Remove-Item", command_tokens)
        self.assertNotIn("Remove-Item", external_tokens)
        self.assertNotIn("./block-comment.txt", host_targets)
        self.assertNotIn("./string-only.txt", host_targets)
        self.assertNotIn("./hashtable-entry.txt", host_targets)
        self.assertNotIn("./here-string.txt", host_targets)
        self.assertNotIn("./literal-here.txt", host_targets)
        self.assertNotIn("https://example.invalid/comment", network_targets)
        self.assertNotIn("https://example.invalid/here", network_targets)


if __name__ == "__main__":
    unittest.main()
