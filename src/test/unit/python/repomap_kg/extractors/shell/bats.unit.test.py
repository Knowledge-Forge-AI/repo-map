import tempfile
import unittest
from pathlib import Path

from repomap_kg.extractors.shell.bats import extract_bats_file_observations
from repomap_kg.graph.discovery import classify_path

from repomap_test_support.bats import (
    BATS_FIXTURE_ROOT as FIXTURE_ROOT,
    first_observation,
    observations_by_kind,
    write_text,
)


class BatsExtractorCoreUnitTests(unittest.TestCase):
    def test_classifies_bats_files_without_routing_helpers_to_bats(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_text(root / "test" / "example.bats", "#!/usr/bin/env bats\n")
            write_text(root / "test" / "test_helper.bash", "# helper\n")
            write_text(root / "scripts" / "generic.sh", "#!/bin/sh\n")
            write_text(root / "test" / "helper.sh", "#!/bin/sh\n")

            bats_info = classify_path(root, root / "test" / "example.bats")
            helper_info = classify_path(root, root / "test" / "test_helper.bash")
            generic_info = classify_path(root, root / "scripts" / "generic.sh")
            shell_helper_info = classify_path(root, root / "test" / "helper.sh")

        self.assertEqual(bats_info.language, "bats")
        self.assertEqual(bats_info.role, "test")
        self.assertNotEqual(bats_info.language, "bash")
        self.assertEqual(helper_info.language, "bash")
        self.assertEqual(generic_info.language, "shell")
        self.assertEqual(shell_helper_info.language, "shell")

    def test_extracts_file_and_static_test_case_observations(self):
        content = (FIXTURE_ROOT / "basic.bats").read_text(encoding="utf-8")

        observations = extract_bats_file_observations("test/basic.bats", content)

        by_kind = observations_by_kind(observations)
        file_observation = by_kind["bats.file"][0]
        self.assertEqual(file_observation.path, "test/basic.bats")
        self.assertEqual(file_observation.confidence, "extracted")
        self.assertEqual(file_observation.metadata["dialect"], "bats")
        self.assertEqual(file_observation.metadata["test_framework"], "bats")
        self.assertEqual(file_observation.metadata["file_type"], "bats")
        self.assertEqual(file_observation.metadata["shebang"], "#!/usr/bin/env bats")
        self.assertEqual(file_observation.metadata["classification_evidence"], ["extension", "shebang"])
        self.assertTrue(file_observation.metadata["static_only"])
        self.assertFalse(file_observation.metadata["shell_executed"])
        self.assertFalse(file_observation.metadata["bats_executed"])

        test_cases = by_kind["bats.test_case"]
        self.assertEqual(
            [item.metadata["test_name"] for item in test_cases],
            ["reports fixture status", "handles quoted fixture name"],
        )
        self.assertEqual({item.metadata["test_name_kind"] for item in test_cases}, {"static"})
        self.assertTrue(all(item.metadata["body_modeled"] is False for item in test_cases))
        self.assertTrue(all(item.metadata["bats_executed"] is False for item in test_cases))

    def test_extracts_hook_observations_without_modeling_hook_bodies(self):
        content = (FIXTURE_ROOT / "hooks.bats").read_text(encoding="utf-8")

        observations = extract_bats_file_observations("test/hooks.bats", content)

        by_kind = observations_by_kind(observations)
        expected = {
            "bats.setup": ("setup", "per_test"),
            "bats.teardown": ("teardown", "per_test"),
            "bats.setup_file": ("setup_file", "per_file"),
            "bats.teardown_file": ("teardown_file", "per_file"),
        }
        for kind, (hook_name, hook_scope) in expected.items():
            with self.subTest(kind=kind):
                observation = by_kind[kind][0]
                self.assertEqual(observation.name, hook_name)
                self.assertEqual(observation.metadata["hook_name"], hook_name)
                self.assertEqual(observation.metadata["hook_scope"], hook_scope)
                self.assertFalse(observation.metadata["body_modeled"])
                self.assertFalse(observation.metadata["bats_executed"])
                self.assertFalse(observation.metadata["shell_executed"])

        self.assertNotIn("shell.host_mutation", by_kind)
        self.assertNotIn("helper_function", {item.name for item in observations})

    def test_extracts_static_and_dynamic_load_observations(self):
        content = (FIXTURE_ROOT / "helpers-and-loads.bats").read_text(encoding="utf-8")

        observations = extract_bats_file_observations(
            "test/helpers-and-loads.bats",
            content,
        )

        loads = observations_by_kind(observations)["bats.load"]
        static_by_name = {item.name: item for item in loads if item.metadata["target_kind"] == "static"}
        self.assertEqual(static_by_name["test_helper"].target, "file:test/test_helper")
        self.assertEqual(static_by_name["./helpers/common"].target, "file:test/helpers/common")
        self.assertEqual(static_by_name["../support/helpers"].target, "file:support/helpers")
        self.assertEqual(static_by_name["test_helper"].metadata["helper_name"], "test_helper")
        self.assertEqual(static_by_name["./helpers/common"].metadata["resolved_path"], "test/helpers/common")

        dynamic = first_observation(
            loads,
            kind="bats.load",
            predicate=lambda item: item.metadata["target_kind"] == "dynamic",
        )
        self.assertIsNone(dynamic.target)
        self.assertEqual(dynamic.name, "[dynamic]")
        self.assertEqual(dynamic.metadata["resolution"], "dynamic")
        self.assertEqual(dynamic.metadata["dynamic_reason"], "computed-load")

    def test_dynamic_test_names_are_bounded_without_modeling_body_commands(self):
        content = (FIXTURE_ROOT / "dynamic.bats").read_text(encoding="utf-8")

        observations = extract_bats_file_observations("test/dynamic.bats", content)

        by_kind = observations_by_kind(observations)
        dynamic_test = first_observation(by_kind["bats.test_case"], kind="bats.test_case", name="[dynamic]")
        self.assertEqual(dynamic_test.confidence, "unknown")
        self.assertEqual(dynamic_test.metadata["test_name_kind"], "dynamic")
        self.assertEqual(dynamic_test.metadata["resolution"], "dynamic")
        self.assertEqual(dynamic_test.metadata["dynamic_reason"], "computed-test-name")
        self.assertFalse(dynamic_test.metadata["body_modeled"])
        self.assertNotIn("shell.host_mutation", by_kind)

        dynamic_load = first_observation(
            by_kind["bats.load"],
            kind="bats.load",
            predicate=lambda item: item.metadata["dynamic_reason"] == "computed-load",
        )
        self.assertIsNone(dynamic_load.target)
        dynamic_run = first_observation(by_kind["bats.run"], kind="bats.run", name="[dynamic]")
        self.assertEqual(dynamic_run.metadata["command_kind"], "dynamic")
        self.assertFalse(dynamic_run.metadata["command_executed"])
