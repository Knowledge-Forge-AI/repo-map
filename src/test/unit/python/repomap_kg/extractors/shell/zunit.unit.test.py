import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repomap_kg.ops.ingestion.bulk import classify_bulk_route
from repomap_kg.graph.discovery import classify_path, discover_observations
from repomap_kg.ops.ingestion.source import _archive_extractor_route
from repomap_kg.extractors.shell.zunit import extract_zunit_file_observations
from repomap_kg.observations.raw import RawObservation


FIXTURE_ROOT = Path(__file__).parents[5] / "fixtures" / "shell" / "zunit"
FAKE_SECRET_MARKERS = (
    "FAKE_ZUNIT_SUITE_TOKEN", "FAKE_ZUNIT_TEST_TOKEN", "FAKE_ZUNIT_ARG_TOKEN",
    "FAKE_ZUNIT_OUTPUT_TOKEN", "FAKE_ZUNIT_SKIP_TOKEN", "FAKE_ZUNIT_TODO_TOKEN",
    "FAKE_ZUNIT_HELPER_TOKEN", "FAKE_ZUNIT_FIXTURE_TOKEN", "FAKE_ZUNIT_STUB_TOKEN",
)


def observations_by_kind(observations: list[RawObservation] | tuple[RawObservation, ...]) -> dict[str, list[RawObservation]]:
    kinds = dict.fromkeys(observation.kind for observation in observations)
    return {kind: [item for item in observations if item.kind == kind] for kind in kinds}


def first_observation(observations, *, kind, name=None, predicate=None):
    for observation in observations:
        if observation.kind != kind:
            continue
        if name is not None and observation.name != name:
            continue
        if predicate is not None and not predicate(observation):
            continue
        return observation
    raise AssertionError(f"missing observation kind={kind!r} name={name!r}")


class ZunitExtractorUnitTests(unittest.TestCase):
    def test_classifies_explicit_zunit_files_without_reclassifying_other_shells(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(root / "test" / "example.zunit", "# static fixture\n")
            self.write(root / "tests" / "zunit" / "nested.zunit", "# static fixture\n")
            self.write(
                root / "tests" / "zunit" / "helper.zsh",
                'describe "helper words"\ntest "not enough" { }\n',
            )
            self.write(
                root / "scripts" / "generic.zsh",
                'describe "not zunit"\ntest "word only" { }\n',
            )
            self.write(root / "scripts" / "invoke.sh", "#!/bin/sh\nzunit ./test/example.zunit\n")
            self.write(root / "test" / "case.bats", "#!/usr/bin/env bats\n")
            self.write(root / "filters" / "report.awk", "# awk fixture\n")
            self.write(root / "scripts" / "tool.bash", "#!/usr/bin/env bash\n")
            self.write(root / "scripts" / "script.ps1", "Write-Output ok\n")
            self.write(root / "zsh" / "plugins" / "plugin.zsh", "# zsh plugin\n")

            infos = {
                relative: classify_path(root, root / relative)
                for relative in (
                    "test/example.zunit", "tests/zunit/nested.zunit", "tests/zunit/helper.zsh",
                    "scripts/generic.zsh", "scripts/invoke.sh", "test/case.bats",
                    "filters/report.awk", "scripts/tool.bash", "scripts/script.ps1", "zsh/plugins/plugin.zsh",
                )
            }

        self.assertEqual(infos["test/example.zunit"].language, "zunit")
        self.assertEqual(infos["test/example.zunit"].role, "test")
        self.assertEqual(infos["tests/zunit/nested.zunit"].language, "zunit")
        self.assertEqual(infos["tests/zunit/nested.zunit"].role, "test")
        self.assertEqual(infos["tests/zunit/helper.zsh"].language, "zsh")
        self.assertEqual(infos["scripts/generic.zsh"].language, "zsh")
        self.assertEqual(infos["scripts/invoke.sh"].language, "shell")
        self.assertEqual(infos["test/case.bats"].language, "bats")
        self.assertEqual(infos["filters/report.awk"].language, "awk")
        self.assertEqual(infos["scripts/tool.bash"].language, "bash")
        self.assertEqual(infos["scripts/script.ps1"].language, "powershell")
        self.assertEqual(infos["zsh/plugins/plugin.zsh"].language, "zsh")

    def test_extracts_file_suite_test_case_and_test_name_observations(self):
        content = (FIXTURE_ROOT / "basic.zunit").read_text(encoding="utf-8")

        observations = extract_zunit_file_observations("test/basic.zunit", content)

        by_kind = observations_by_kind(observations)
        file_observation = by_kind["zunit.file"][0]
        self.assertEqual(file_observation.path, "test/basic.zunit")
        self.assertEqual(file_observation.metadata["language"], "zsh")
        self.assertEqual(file_observation.metadata["dialect"], "zsh")
        self.assertEqual(file_observation.metadata["test_framework"], "zunit")
        self.assertEqual(file_observation.metadata["file_type"], "test")
        self.assertEqual(file_observation.metadata["classification_evidence"], ["extension"])
        self.assertEqual(file_observation.metadata["parser"], "stdlib-static-scanner")
        self.assertTrue(file_observation.metadata["static_only"])
        for key in (
            "shell_executed", "zsh_executed", "zunit_executed", "tests_executed",
            "assertions_executed", "commands_executed", "fixtures_loaded", "mocks_applied",
        ):
            self.assertFalse(file_observation.metadata[key])

        suite = by_kind["zunit.suite"][0]
        self.assertEqual(suite.name, "example tool")
        self.assertEqual(suite.metadata["suite_name"], "example tool")
        self.assertEqual(suite.metadata["suite_name_kind"], "static")
        self.assertEqual(suite.metadata["suite_kind"], "describe")
        self.assertFalse(suite.metadata["body_modeled"])
        self.assertFalse(suite.metadata["suite_executed"])
        self.assertFalse(suite.metadata["tests_executed"])

        tests = by_kind["zunit.test_case"]
        self.assertEqual(
            [item.metadata["test_name"] for item in tests],
            ["reports version", "handles missing input"],
        )
        self.assertEqual({item.metadata["test_name_kind"] for item in tests}, {"static"})
        self.assertEqual({item.metadata["syntax"] for item in tests}, {"test_block"})
        self.assertEqual({item.metadata["enclosing_suite"] for item in tests}, {"example tool"})
        self.assertTrue(all(item.metadata["body_modeled"] is False for item in tests))
        self.assertTrue(all(item.metadata["test_intent"] is True for item in tests))
        self.assertTrue(all(item.metadata["test_executed"] is False for item in tests))
        self.assertTrue(all(item.metadata["zunit_executed"] is False for item in tests))

        test_names = by_kind["zunit.test_name"]
        self.assertEqual([item.name for item in test_names], ["reports version", "handles missing input"])
        self.assertTrue(all(item.metadata["name_kind"] == "static" for item in test_names))
        self.assertTrue(all(item.metadata["test_executed"] is False for item in test_names))

        self.assertIn("zunit.assertion", by_kind)
        self.assertIn("zunit.expectation", by_kind)
        self.assertIn("zunit.command_under_test", by_kind)
        runtime_or_unrelated_kinds = {
            "zunit.setup", "zunit.teardown", "zunit.before_each", "zunit.after_each",
            "zunit.hook", "zunit.helper", "zunit.mock", "zunit.stub", "zunit.skip",
            "zunit.todo", "shell.command", "shell.host_mutation", "shell.network_call",
            "shell.package_manager",
        }
        self.assertTrue(runtime_or_unrelated_kinds.isdisjoint(by_kind))

    def test_dynamic_tests_are_bounded_without_executing_generated_forms(self):
        content = (FIXTURE_ROOT / "dynamic.zunit").read_text(encoding="utf-8")

        observations = extract_zunit_file_observations("test/dynamic.zunit", content)

        by_kind = observations_by_kind(observations)
        dynamic_tests = by_kind["zunit.dynamic_test"]
        reasons = {item.metadata["dynamic_reason"] for item in dynamic_tests}
        self.assertIn("generated_loop", reasons)
        self.assertIn("dynamic_test_name", reasons)
        self.assertIn("eval_generated", reasons)
        self.assertTrue(all(item.metadata["test_count_known"] is False for item in dynamic_tests))
        self.assertTrue(all(item.metadata["generated_tests_executed"] is False for item in dynamic_tests))
        self.assertTrue(all(item.metadata["zunit_executed"] is False for item in dynamic_tests))
        self.assertTrue(all(item.metadata["shell_executed"] is False for item in dynamic_tests))
        parameterized = by_kind["zunit.parameterized_case"][0]
        self.assertEqual(parameterized.metadata["parameter_name"], "case_name")
        self.assertEqual(parameterized.metadata["static_value_count"], 2)
        self.assertFalse(parameterized.metadata["generated_test_count_known"])
        self.assertFalse(parameterized.metadata["parameterized_cases_executed"])
        dynamic_commands = [
            item
            for item in by_kind["zunit.command_under_test"]
            if item.metadata["command_kind"] == "dynamic"
        ]
        self.assertTrue(dynamic_commands)
        self.assertTrue(all(item.metadata["command_executed"] is False for item in dynamic_commands))
        dynamic_helpers = [
            item for item in by_kind["zunit.helper"] if item.metadata["target_kind"] == "dynamic"
        ]
        dynamic_fixtures = [
            item
            for item in by_kind["zunit.fixture_reference"]
            if item.metadata["target_kind"] == "dynamic"
        ]
        self.assertTrue(dynamic_helpers)
        self.assertTrue(dynamic_fixtures)
        self.assertNotIn("shell.command", by_kind)

    def test_hooks_are_test_intent_not_runtime_side_effects(self):
        content = (FIXTURE_ROOT / "hooks.zunit").read_text(encoding="utf-8")

        observations = extract_zunit_file_observations("test/hooks.zunit", content)

        by_kind = observations_by_kind(observations)
        expected_hooks = {
            "zunit.setup": ("setup", "setup"),
            "zunit.teardown": ("teardown", "teardown"),
            "zunit.before_each": ("before_each", "before_each"),
            "zunit.after_each": ("after_each", "after_each"),
        }
        for kind, (hook_name, hook_kind) in expected_hooks.items():
            observation = by_kind[kind][0]
            self.assertEqual(observation.metadata["hook_name"], hook_name)
            self.assertEqual(observation.metadata["hook_kind"], hook_kind)
            self.assertEqual(observation.metadata["hook_scope"], "file")
            self.assertFalse(observation.metadata["body_modeled"])
            self.assertFalse(observation.metadata["hook_executed"])
            self.assertFalse(observation.metadata["tests_executed"])
            self.assertFalse(observation.metadata["zunit_executed"])
            self.assertFalse(observation.metadata["shell_executed"])

        forbidden_runtime_kinds = {
            "shell.host_mutation", "shell.network_call", "shell.package_manager", "shell.file_read", "shell.file_write",
        }
        self.assertTrue(forbidden_runtime_kinds.isdisjoint(by_kind))

    def test_assertions_expectations_and_commands_under_test_are_non_executed(self):
        content = (FIXTURE_ROOT / "assertions-and-commands.zunit").read_text(encoding="utf-8")

        observations = extract_zunit_file_observations("test/assertions-and-commands.zunit", content)

        by_kind = observations_by_kind(observations)
        assertion_names = {item.metadata["assertion_name"] for item in by_kind["zunit.assertion"]}
        self.assertEqual(
            assertion_names,
            {"assert_success", "assert_equal", "assert_output", "refute_output", "assert_file_exists", "assert_dir_exists"},
        )
        self.assertTrue(
            all(item.metadata["assertion_executed"] is False for item in by_kind["zunit.assertion"])
        )
        self.assertTrue(
            all(item.metadata["test_passed_known"] is False for item in by_kind["zunit.assertion"])
        )
        expectation_kinds = {item.metadata["expectation_kind"] for item in by_kind["zunit.expectation"]}
        self.assertTrue({"status", "output", "file", "directory"}.issubset(expectation_kinds))
        self.assertTrue(
            all(item.metadata["expectation_checked"] is False for item in by_kind["zunit.expectation"])
        )
        commands = by_kind["zunit.command_under_test"]
        self.assertGreaterEqual(len(commands), 3)
        self.assertIn("run_wrapper", {item.metadata["command_kind"] for item in commands})
        self.assertIn("direct_command", {item.metadata["command_kind"] for item in commands})
        self.assertTrue(all(item.metadata["test_intent"] is True for item in commands))
        self.assertTrue(all(item.metadata["command_under_test"] is True for item in commands))
        self.assertTrue(all(item.metadata["command_executed"] is False for item in commands))
        self.assertTrue(all(item.metadata["stdout_known"] is False for item in commands))
        self.assertTrue(all(item.metadata["stderr_known"] is False for item in commands))
        self.assertTrue(all(item.metadata["status_known"] is False for item in commands))
        fixture_refs = by_kind["zunit.fixture_reference"]
        self.assertTrue(any(item.metadata.get("fixture_path") == "./fixtures/input.txt" for item in fixture_refs))
        self.assertTrue(all(item.metadata["fixture_loaded"] is False for item in fixture_refs))
        self.assertTrue(all(item.metadata["filesystem_checked"] is False for item in fixture_refs))
        forbidden_runtime_kinds = {
            "shell.host_mutation", "shell.network_call", "shell.package_manager", "shell.file_read", "shell.file_write",
        }
        self.assertTrue(forbidden_runtime_kinds.isdisjoint(by_kind))

    def test_helpers_fixtures_mocks_and_stubs_are_bounded_references(self):
        content = (FIXTURE_ROOT / "helpers-fixtures-mocks.zunit").read_text(encoding="utf-8")

        observations = extract_zunit_file_observations("test/helpers-fixtures-mocks.zunit", content)

        by_kind = observations_by_kind(observations)
        helpers = by_kind["zunit.helper"]
        helper_paths = {item.metadata.get("helper_path") for item in helpers}
        self.assertIn("./helpers/common.zsh", helper_paths)
        self.assertIn("./helpers/assertions.zsh", helper_paths)
        self.assertIn("./helpers/extra.zsh", helper_paths)
        self.assertTrue(all(item.metadata["helper_loaded"] is False for item in helpers))
        self.assertTrue(all(item.metadata["file_read"] is False for item in helpers))
        self.assertTrue(all(item.metadata["filesystem_checked"] is False for item in helpers))

        fixture_refs = by_kind["zunit.fixture_reference"]
        fixture_paths = {item.metadata.get("fixture_path") for item in fixture_refs}
        self.assertIn("./fixtures/public-input.txt", fixture_paths)
        self.assertIn("./fixtures/extra-input.txt", fixture_paths)
        self.assertTrue(all(item.metadata["fixture_loaded"] is False for item in fixture_refs))
        self.assertTrue(all(item.metadata["file_read"] is False for item in fixture_refs))
        self.assertTrue(all(item.metadata["filesystem_checked"] is False for item in fixture_refs))

        mocks = by_kind["zunit.mock"]
        stubs = by_kind["zunit.stub"]
        self.assertIn("git", {item.metadata["target_command"] for item in mocks})
        self.assertIn("docker", {item.metadata["target_command"] for item in mocks})
        self.assertIn("curl", {item.metadata["target_command"] for item in stubs})
        self.assertTrue(all(item.metadata["mocks_applied"] is False for item in mocks))
        self.assertTrue(all(item.metadata["target_executed"] is False for item in mocks + stubs))
        self.assertTrue(all(item.metadata["command_executed"] is False for item in mocks + stubs))
        self.assertTrue(all(item.metadata["shell_executed"] is False for item in mocks + stubs))
        self.assertNotIn("shell.network_call", by_kind)
        self.assertNotIn("shell.package_manager", by_kind)

    def test_skips_and_todos_do_not_imply_runtime_status(self):
        content = (FIXTURE_ROOT / "skips-and-todos.zunit").read_text(encoding="utf-8")

        observations = extract_zunit_file_observations("test/skips-and-todos.zunit", content)

        by_kind = observations_by_kind(observations)
        skip = by_kind["zunit.skip"][0]
        todo = by_kind["zunit.todo"][0]
        self.assertEqual(skip.metadata["reason_kind"], "static")
        self.assertEqual(todo.metadata["reason_kind"], "static")
        self.assertEqual(skip.metadata["reason_summary"], "requires network")
        self.assertEqual(todo.metadata["reason_summary"], "add edge case")
        self.assertFalse(skip.metadata["skip_executed"])
        self.assertFalse(todo.metadata["todo_executed"])
        self.assertFalse(skip.metadata["test_status_known"])
        self.assertFalse(todo.metadata["test_status_known"])

    def test_redacts_secret_like_suite_and_test_names(self):
        content = (FIXTURE_ROOT / "redaction.zunit").read_text(encoding="utf-8")

        observations = extract_zunit_file_observations("test/redaction.zunit", content)
        serialized = json.dumps([item.to_dict() for item in observations], sort_keys=True)

        for marker in FAKE_SECRET_MARKERS:
            self.assertNotIn(marker, serialized)
        by_kind = observations_by_kind(observations)
        suite = by_kind["zunit.suite"][0]
        test = by_kind["zunit.test_case"][0]
        test_name = by_kind["zunit.test_name"][0]
        self.assertEqual(suite.name, "[redacted]")
        self.assertEqual(test.name, "[redacted]")
        self.assertEqual(test_name.name, "[redacted]")
        self.assertEqual(suite.metadata["suite_name_kind"], "redacted")
        self.assertEqual(test.metadata["test_name_kind"], "redacted")
        self.assertEqual(test_name.metadata["name_kind"], "redacted")
        self.assertFalse(suite.metadata["raw_value_stored"])
        self.assertFalse(test.metadata["raw_value_stored"])
        self.assertFalse(test_name.metadata["raw_name_stored"])
        self.assertIn("zunit.secret_like", by_kind)
        secret_sources = {item.metadata["secret_source"] for item in by_kind["zunit.secret_like"]}
        self.assertTrue(
            {
                "suite_name", "test_name", "command_argument", "expected_value",
                "helper_path", "fixture_path", "stub_behavior", "skip_reason", "todo_reason",
            }.issubset(secret_sources)
        )
        redacted_expectation = first_observation(
            by_kind["zunit.expectation"],
            kind="zunit.expectation",
            predicate=lambda item: item.metadata["expected_value_kind"] == "redacted",
        )
        self.assertFalse(redacted_expectation.metadata["raw_expected_value_stored"])
        redacted_command = first_observation(
            by_kind["zunit.command_under_test"],
            kind="zunit.command_under_test",
            predicate=lambda item: item.metadata["argument_summary_kind"] == "redacted",
        )
        self.assertFalse(redacted_command.metadata["command_executed"])

    def test_false_positive_boundaries_skip_comments_strings_heredocs_arrays_and_case_labels(self):
        content = (FIXTURE_ROOT / "false-positives.zunit").read_text(encoding="utf-8")

        observations = extract_zunit_file_observations("test/false-positives.zunit", content)

        by_kind = observations_by_kind(observations)
        self.assertEqual(len(by_kind["zunit.file"]), 1)
        for unexpected in (
            "zunit.suite", "zunit.test_case", "zunit.test_name", "zunit.assertion",
            "zunit.mock", "zunit.stub", "zunit.skip", "zunit.todo", "zunit.command_under_test",
            "zunit.expectation", "zunit.helper", "zunit.fixture_reference",
            "shell.command", "shell.host_mutation",
        ):
            self.assertNotIn(unexpected, by_kind)

    def test_discovery_routes_zunit_files_through_zunit_extractor_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(
                root / "test" / "basic.zunit",
                (FIXTURE_ROOT / "basic.zunit").read_text(encoding="utf-8"),
            )

            observations = discover_observations(root)

        file_info = next(item for item in observations if item.path == "test/basic.zunit" and item.kind == "file")
        self.assertEqual(file_info.metadata["language"], "zunit")
        self.assertTrue(any(item.path == "test/basic.zunit" and item.kind == "zunit.file" for item in observations))
        self.assertFalse(any(item.path == "test/basic.zunit" and item.kind == "zsh.script" for item in observations))
        self.assertFalse(any(item.path == "test/basic.zunit" and item.metadata.get("dialect") == "zsh" and item.kind.startswith("shell.") for item in observations))

    def test_bulk_and_archive_routes_include_zunit(self):
        self.assertEqual(classify_bulk_route(Path("test/basic.zunit")), "zunit")
        self.assertEqual(classify_bulk_route(Path("tests/zunit/basic.zunit")), "zunit")
        self.assertEqual(_archive_extractor_route(Path("test/basic.zunit")), "zunit")
        self.assertEqual(_archive_extractor_route(Path("scripts/generic.zsh")), "zsh")

    def test_extractor_does_not_invoke_subprocess_or_shells(self):
        content = (FIXTURE_ROOT / "basic.zunit").read_text(encoding="utf-8")

        with patch.object(subprocess, "run", side_effect=AssertionError("no subprocess")):
            observations = extract_zunit_file_observations("test/basic.zunit", content)

        self.assertTrue(observations)

    @staticmethod
    def write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
