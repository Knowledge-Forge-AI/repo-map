import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repomap_kg.extractors.shell.bats import extract_bats_file_observations
from repomap_kg.graph.discovery import discover_observations
from repomap_kg.ops.ingestion.bulk import classify_bulk_route
from repomap_kg.ops.ingestion.source import _archive_extractor_route

from repomap_test_support.bats import (
    BATS_FIXTURE_ROOT as FIXTURE_ROOT,
    first_observation,
    observations_by_kind,
    write_text,
)


class BatsExtractorAdvancedUnitTests(unittest.TestCase):
    def test_bats2_library_loads_and_helper_references_are_static_or_bounded(self):
        content = (FIXTURE_ROOT / "helpers-and-libraries.bats").read_text(encoding="utf-8")

        observations = extract_bats_file_observations(
            "test/helpers-and-libraries.bats",
            content,
        )

        by_kind = observations_by_kind(observations)
        libraries = by_kind["bats.library_load"]
        static_libraries = {
            item.metadata["library_name"]
            for item in libraries
            if item.metadata["target_kind"] == "static"
        }
        self.assertEqual(static_libraries, {"bats-support", "bats-assert", "bats-file"})
        dynamic_library = first_observation(
            libraries,
            kind="bats.library_load",
            predicate=lambda item: item.metadata["target_kind"] == "dynamic",
        )
        self.assertEqual(dynamic_library.name, "[dynamic]")
        self.assertEqual(dynamic_library.metadata["resolution"], "dynamic")
        self.assertFalse(dynamic_library.metadata["bats_executed"])

        helper_loads = [
            item for item in by_kind["bats.helper_reference"]
            if item.metadata["reference_kind"] == "load_target"
        ]
        self.assertEqual({item.metadata["helper_name"] for item in helper_loads}, {"test_helper", "common"})

        helper_run = first_observation(
            by_kind["bats.helper_reference"],
            kind="bats.helper_reference",
            name="helper_read_fixture",
        )
        self.assertEqual(helper_run.metadata["reference_kind"], "command_under_test")
        self.assertFalse(helper_run.metadata["helper_executed"])
        self.assertTrue(helper_run.metadata["test_intent"])

    def test_bats2_run_wrappers_are_command_under_test_intent_only(self):
        content = (FIXTURE_ROOT / "run-and-assertions.bats").read_text(encoding="utf-8")

        observations = extract_bats_file_observations(
            "test/run-and-assertions.bats",
            content,
        )

        by_kind = observations_by_kind(observations)
        git_run = first_observation(by_kind["bats.run"], kind="bats.run", name="git")
        self.assertEqual(git_run.metadata["command_token"], "git")
        self.assertEqual(git_run.metadata["command_kind"], "static")
        self.assertEqual(git_run.metadata["argument_count"], 2)
        self.assertEqual(git_run.metadata["test_context"], "test_case")
        self.assertEqual(git_run.metadata["test_case_name"], "records command-under-test intent")
        self.assertTrue(git_run.metadata["command_under_test"])
        self.assertTrue(git_run.metadata["test_intent"])
        self.assertFalse(git_run.metadata["command_executed"])
        self.assertFalse(git_run.metadata["shell_executed"])

        status_run = first_observation(
            by_kind["bats.run"],
            kind="bats.run",
            predicate=lambda item: item.metadata.get("expected_status") == 1,
        )
        self.assertEqual(status_run.metadata["expected_status_source"], "run_flag")

        negated = first_observation(
            by_kind["bats.run"],
            kind="bats.run",
            predicate=lambda item: item.metadata.get("negated") is True,
        )
        self.assertTrue(negated.metadata["separate_stderr"])
        self.assertFalse(negated.metadata["command_executed"])

        self.assertNotIn("shell.host_mutation", by_kind)
        self.assertNotIn("shell.network_call", by_kind)

    def test_bats2_assertions_refutations_and_expectations_are_modeled(self):
        content = (FIXTURE_ROOT / "run-and-assertions.bats").read_text(encoding="utf-8")

        observations = extract_bats_file_observations(
            "test/run-and-assertions.bats",
            content,
        )

        by_kind = observations_by_kind(observations)
        assertion_families = {
            (item.metadata["assertion_name"], item.metadata["assertion_family"], item.metadata["mode"])
            for item in by_kind["bats.assertion"]
        }
        self.assertIn(("assert_success", "status", "exact"), assertion_families)
        self.assertIn(("assert_failure", "status", "exact"), assertion_families)
        self.assertIn(("assert_equal", "equality", "exact"), assertion_families)
        self.assertIn(("assert_output", "output", "partial"), assertion_families)
        self.assertIn(("assert_line", "line", "partial"), assertion_families)
        self.assertIn(("assert_file_exists", "file", "exact"), assertion_families)
        self.assertIn(("assert_dir_exists", "directory", "exact"), assertion_families)

        refutations = {
            (item.metadata["assertion_name"], item.metadata["assertion_family"], item.metadata["mode"])
            for item in by_kind["bats.refutation"]
        }
        self.assertIn(("refute_output", "output", "partial"), refutations)
        self.assertIn(("refute_line", "line", "exact"), refutations)

        output_expectations = {
            (item.metadata["expectation_kind"], item.metadata["mode"], item.metadata["positive"])
            for item in by_kind["bats.output_expectation"]
        }
        self.assertIn(("output", "partial", True), output_expectations)
        self.assertIn(("output", "partial", False), output_expectations)
        self.assertIn(("line", "partial", True), output_expectations)
        self.assertIn(("line", "exact", False), output_expectations)

        status_expectations = {
            (item.metadata["source"], item.metadata.get("expected_status"), item.metadata.get("expected_success"))
            for item in by_kind["bats.status_expectation"]
        }
        self.assertIn(("run_flag", 1, False), status_expectations)
        self.assertIn(("assertion", 0, True), status_expectations)
        self.assertIn(("assertion", None, False), status_expectations)
        self.assertIn(("equality", 1, False), status_expectations)

    def test_bats2_skip_and_fixture_references_are_bounded(self):
        content = (FIXTURE_ROOT / "skip-and-fixtures.bats").read_text(encoding="utf-8")

        observations = extract_bats_file_observations(
            "test/skip-and-fixtures.bats",
            content,
        )

        by_kind = observations_by_kind(observations)
        skip_kinds = {item.metadata["reason_kind"] for item in by_kind["bats.skip"]}
        self.assertIn("static", skip_kinds)
        self.assertIn("omitted", skip_kinds)
        self.assertIn("dynamic", skip_kinds)
        static_skip = first_observation(
            by_kind["bats.skip"],
            kind="bats.skip",
            predicate=lambda item: item.metadata["reason_kind"] == "static",
        )
        self.assertIn("requires disabled", static_skip.metadata["reason_summary"])
        self.assertFalse(static_skip.metadata["skip_executed"])

        fixture_refs = by_kind["bats.fixture_reference"]
        repo_refs = {
            item.metadata.get("resolved_path")
            for item in fixture_refs
            if item.metadata["fixture_kind"] == "repo_fixture"
        }
        self.assertIn("test/fixtures/sample.txt", repo_refs)
        self.assertIn("test/fixtures", repo_refs)
        temp_refs = [
            item for item in fixture_refs
            if item.metadata["fixture_kind"] == "temp_fixture"
        ]
        self.assertGreaterEqual(len(temp_refs), 2)
        self.assertTrue(all(item.metadata["resolution"] == "temp" for item in temp_refs))
        self.assertTrue(all(item.metadata["filesystem_checked"] is False for item in fixture_refs))
        self.assertTrue(all(item.metadata["file_created"] is False for item in fixture_refs))

    def test_bats2_redacts_secret_like_values_from_serialized_observations(self):
        content = (FIXTURE_ROOT / "redaction.bats").read_text(encoding="utf-8")

        observations = extract_bats_file_observations("test/redaction.bats", content)

        payload = json.dumps([item.to_dict() for item in observations], sort_keys=True)
        self.assertNotIn("FAKE_BATS_OUTPUT_TOKEN", payload)
        self.assertNotIn("FAKE_BATS_RUN_TOKEN", payload)
        self.assertNotIn("FAKE_BATS_SKIP_SECRET", payload)
        self.assertNotIn("FAKE_BATS_HELPER_TOKEN", payload)
        by_kind = observations_by_kind(observations)
        self.assertIn("shell.secret_like", by_kind)
        self.assertTrue(
            any(item.metadata.get("redacted") is True for item in by_kind["bats.output_expectation"])
        )

    def test_discovery_routes_bats_files_through_bats_extractor(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_text(
                root / "test" / "basic.bats",
                (FIXTURE_ROOT / "basic.bats").read_text(encoding="utf-8"),
            )
            write_text(root / "test" / "test_helper.bash", "# helper\n")

            observations = discover_observations(root)

        by_kind = observations_by_kind(observations)
        file_observation = first_observation(observations, kind="file", name=None)
        self.assertIn("bats.file", by_kind)
        self.assertIn("bats.test_case", by_kind)
        self.assertEqual(
            next(item for item in observations if item.path == "test/basic.bats" and item.kind == "file").metadata["language"],
            "bats",
        )
        self.assertFalse(any(item.path == "test/basic.bats" and item.kind == "shell.script" for item in observations))
        self.assertFalse(any(item.path == "test/basic.bats" and item.metadata.get("dialect") == "bash" for item in observations))
        self.assertEqual(file_observation.kind, "file")

    def test_local_ingestion_route_tables_include_bats_without_bash_routing(self):
        self.assertEqual(classify_bulk_route(Path("test/basic.bats")), "bats")
        self.assertEqual(_archive_extractor_route(Path("test/basic.bats")), "bats")
        self.assertEqual(classify_bulk_route(Path("test/test_helper.bash")), "bash")

    def test_false_positive_boundaries_skip_comments_strings_arrays_heredocs_and_case_labels(self):
        content = (FIXTURE_ROOT / "false-positives.bats").read_text(encoding="utf-8")

        observations = extract_bats_file_observations("test/false-positives.bats", content)

        by_kind = observations_by_kind(observations)
        self.assertEqual(len(by_kind.get("bats.test_case", ())), 0)
        self.assertEqual(len(by_kind.get("bats.load", ())), 0)
        self.assertNotIn("bats.run", by_kind)
        self.assertNotIn("bats.assertion", by_kind)
        self.assertNotIn("bats.refutation", by_kind)
        self.assertNotIn("bats.skip", by_kind)
        self.assertNotIn("bats.library_load", by_kind)
        self.assertNotIn("bats.fixture_reference", by_kind)
        self.assertNotIn("bats.helper_reference", by_kind)
        self.assertNotIn("bats.output_expectation", by_kind)
        self.assertNotIn("bats.status_expectation", by_kind)
        self.assertNotIn("shell.host_mutation", by_kind)

    def test_extractor_does_not_invoke_subprocess_or_shells(self):
        content = (FIXTURE_ROOT / "basic.bats").read_text(encoding="utf-8")

        with patch.object(subprocess, "run", side_effect=AssertionError("subprocess invoked")):
            observations = extract_bats_file_observations("test/basic.bats", content)

        self.assertIn("bats.file", {item.kind for item in observations})

    def test_serialized_observations_do_not_include_fake_secret_like_values(self):
        content = (
            "#!/usr/bin/env bats\n"
            "# Static extraction fixture only. Do not execute.\n"
            "@test \"FAKE_BATS_TOKEN\" {\n"
            "    load \"FAKE_BATS_SECRET_HELPER\"\n"
            "}\n"
        )

        observations = extract_bats_file_observations("test/redaction.bats", content)

        payload = json.dumps([item.to_dict() for item in observations], sort_keys=True)
        self.assertNotIn("FAKE_BATS_TOKEN", payload)
        self.assertNotIn("FAKE_BATS_SECRET_HELPER", payload)
