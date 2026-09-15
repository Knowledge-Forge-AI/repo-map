import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repomap_kg.canonicalization.main import canonicalize_observations
    from repomap_kg.observations.raw import RawObservation
else:
    from repomap_kg.canonicalization import canonicalize_observations
from repomap_kg.graph.keys import (
    file_key,
    tool_key,
    zunit_assertion_key,
    zunit_command_under_test_key,
    zunit_expectation_key,
    zunit_file_key,
    zunit_hook_key,
    zunit_mock_key,
    zunit_stub_key,
    zunit_suite_key,
    zunit_test_case_key,
)
from repomap_kg.storage import prepare_canonical_load
from repomap_kg.extractors.shell.zunit import extract_zunit_file_observations
from repomap_kg.graph.readback.zunit import summarize_zunit_evidence


FIXTURE_ROOT = Path(__file__).parents[5] / "fixtures" / "shell" / "zunit"
FIXTURE_NAMES = (
    "basic.zunit",
    "suites-and-cases.zunit",
    "dynamic.zunit",
    "redaction.zunit",
    "false-positives.zunit",
    "hooks.zunit",
    "assertions-and-commands.zunit",
    "helpers-fixtures-mocks.zunit",
    "skips-and-todos.zunit",
)
FAKE_SECRET_MARKERS = (
    "FAKE_ZUNIT_SUITE_TOKEN",
    "FAKE_ZUNIT_TEST_TOKEN",
    "FAKE_ZUNIT_ARG_TOKEN",
    "FAKE_ZUNIT_OUTPUT_TOKEN",
    "FAKE_ZUNIT_SKIP_TOKEN",
    "FAKE_ZUNIT_TODO_TOKEN",
    "FAKE_ZUNIT_HELPER_TOKEN",
    "FAKE_ZUNIT_FIXTURE_TOKEN",
    "FAKE_ZUNIT_STUB_TOKEN",
)


def fixture_observations(*names: str):
    observations: list[RawObservation] = []
    selected = names or FIXTURE_NAMES
    for name in selected:
        content = (FIXTURE_ROOT / name).read_text(encoding="utf-8")
        observations.extend(
            extract_zunit_file_observations(f"fixtures/shell/zunit/{name}", content)
        )
    return tuple(observations)


def edge_pairs(payload):
    return {
        (edge["source_key"], edge["kind"], edge["target_key"])
        for edge in payload["edges"]
    }


class ZunitCanonicalizationUnitTests(unittest.TestCase):
    def test_zunit_fixture_observations_create_selected_canonical_graph_evidence(self):
        observations = fixture_observations()

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(
            [
                diagnostic
                for diagnostic in payload["diagnostics"]
                if diagnostic["category"] == "unsupported_raw_observation_kind"
            ],
            [],
        )

        node_keys = {node["canonical_key"] for node in payload["nodes"]}
        basic_file = zunit_file_key("fixtures/shell/zunit/basic.zunit")
        basic_suite = zunit_suite_key("fixtures/shell/zunit/basic.zunit", "example tool")
        reports_test = zunit_test_case_key(
            "fixtures/shell/zunit/basic.zunit",
            "reports version",
        )
        command_test = zunit_test_case_key(
            "fixtures/shell/zunit/assertions-and-commands.zunit",
            "captures normal output",
        )
        hooks_file = zunit_file_key("fixtures/shell/zunit/hooks.zunit")
        setup_hook = zunit_hook_key("fixtures/shell/zunit/hooks.zunit", "setup", 3)
        assertion = zunit_assertion_key(
            "fixtures/shell/zunit/assertions-and-commands.zunit",
            7,
            "assert_success",
        )
        expectation = zunit_expectation_key(
            "fixtures/shell/zunit/assertions-and-commands.zunit",
            9,
            "output",
        )
        command = zunit_command_under_test_key(
            "fixtures/shell/zunit/assertions-and-commands.zunit",
            6,
            "./bin/example",
        )
        mock = zunit_mock_key(
            "fixtures/shell/zunit/helpers-fixtures-mocks.zunit",
            6,
            "git",
        )
        stub = zunit_stub_key(
            "fixtures/shell/zunit/helpers-fixtures-mocks.zunit",
            7,
            "curl",
        )

        self.assertIn(basic_file, node_keys)
        self.assertIn(basic_suite, node_keys)
        self.assertIn(reports_test, node_keys)
        self.assertIn(hooks_file, node_keys)
        self.assertIn(setup_hook, node_keys)
        self.assertIn(assertion, node_keys)
        self.assertIn(expectation, node_keys)
        self.assertIn(command, node_keys)
        self.assertIn(mock, node_keys)
        self.assertIn(stub, node_keys)
        self.assertIn(file_key("fixtures/shell/zunit/helpers/common.zsh"), node_keys)
        self.assertIn(file_key("fixtures/shell/zunit/fixtures/public-input.txt"), node_keys)
        self.assertIn(tool_key("./bin/example"), node_keys)

        pairs = edge_pairs(payload)
        self.assertIn(
            (file_key("fixtures/shell/zunit/basic.zunit"), "defines", basic_file),
            pairs,
        )
        self.assertIn((basic_file, "contains", basic_suite), pairs)
        self.assertIn((basic_suite, "has_test_case", reports_test), pairs)
        self.assertIn((hooks_file, "has_hook", setup_hook), pairs)
        self.assertIn((command_test, "command_under_test", tool_key("./bin/example")), pairs)
        self.assertIn((command_test, "has_assertion", assertion), pairs)
        self.assertIn((command_test, "expects", expectation), pairs)
        self.assertIn(
            (
                zunit_file_key("fixtures/shell/zunit/helpers-fixtures-mocks.zunit"),
                "uses_helper",
                file_key("fixtures/shell/zunit/helpers/common.zsh"),
            ),
            pairs,
        )
        self.assertIn(
            (
                zunit_test_case_key(
                    "fixtures/shell/zunit/helpers-fixtures-mocks.zunit",
                    "uses a static fixture",
                ),
                "uses_fixture",
                file_key("fixtures/shell/zunit/fixtures/public-input.txt"),
            ),
            pairs,
        )
        self.assertIn(
            (
                zunit_file_key("fixtures/shell/zunit/helpers-fixtures-mocks.zunit"),
                "uses_mock",
                mock,
            ),
            pairs,
        )
        self.assertIn(
            (
                zunit_file_key("fixtures/shell/zunit/helpers-fixtures-mocks.zunit"),
                "uses_stub",
                stub,
            ),
            pairs,
        )

    def test_dynamic_raw_only_and_runtime_sensitive_zunit_observations_remain_bounded(self):
        observations = fixture_observations()

        result = canonicalize_observations(observations)
        payload = result.to_dict()
        serialized = json.dumps(payload, sort_keys=True)

        self.assertTrue(result.ok)
        self.assertEqual(
            [
                diagnostic
                for diagnostic in payload["diagnostics"]
                if diagnostic["category"] == "unsupported_raw_observation_kind"
            ],
            [],
        )
        self.assertNotIn("tool:%24DYNAMIC_COMMAND", serialized)
        self.assertNotIn("file:%24DYNAMIC_HELPER", serialized)
        self.assertNotIn("file:%24DYNAMIC_FIXTURE", serialized)
        self.assertNotIn("host.category:", serialized)
        self.assertNotIn('"kind": "executes"', serialized)
        self.assertNotIn('"kind": "mutates_host"', serialized)
        self.assertNotIn('"kind": "network_call"', serialized)
        self.assertNotIn('"kind": "package_manager"', serialized)

        raw_evidence_kinds = {evidence["raw_kind"] for evidence in payload["evidence"]}
        self.assertTrue(
            {
                "zunit.test_name",
                "zunit.dynamic_test",
                "zunit.parameterized_case",
                "zunit.skip",
                "zunit.todo",
                "zunit.secret_like",
            }.issubset(raw_evidence_kinds)
        )
        for marker in FAKE_SECRET_MARKERS:
            self.assertNotIn(marker, serialized)

    def test_zunit_fixture_dogfood_summary_is_bounded_and_count_only(self):
        observations = fixture_observations()
        result = canonicalize_observations(observations)

        summary = summarize_zunit_evidence(observations, result)
        payload = summary.to_dict()
        serialized = json.dumps(payload, sort_keys=True)

        self.assertGreater(payload["raw_observations"], 0)
        self.assertGreater(payload["zunit"]["files"], 0)
        self.assertGreater(payload["zunit"]["suites"], 0)
        self.assertGreater(payload["zunit"]["test_cases"], 0)
        self.assertGreater(payload["zunit"]["test_names"], 0)
        self.assertGreater(payload["zunit"]["dynamic_tests"], 0)
        self.assertGreater(payload["zunit"]["setups"], 0)
        self.assertGreater(payload["zunit"]["teardowns"], 0)
        self.assertGreater(payload["zunit"]["before_each"], 0)
        self.assertGreater(payload["zunit"]["after_each"], 0)
        self.assertGreater(payload["zunit"]["assertions"], 0)
        self.assertGreater(payload["zunit"]["expectations"], 0)
        self.assertGreater(payload["zunit"]["commands_under_test"], 0)
        self.assertGreater(payload["zunit"]["helpers"], 0)
        self.assertGreater(payload["zunit"]["fixture_references"], 0)
        self.assertGreater(payload["zunit"]["mocks"], 0)
        self.assertGreater(payload["zunit"]["stubs"], 0)
        self.assertGreater(payload["zunit"]["skips"], 0)
        self.assertGreater(payload["zunit"]["todos"], 0)
        self.assertGreater(payload["zunit"]["parameterized_cases"], 0)
        self.assertGreater(payload["zunit"]["secret_like_redacted"], 0)
        self.assertGreater(payload["zunit"]["dynamic_or_unknown"], 0)
        self.assertGreater(payload["canonical"]["nodes"], 0)
        self.assertGreater(payload["canonical"]["edges"], 0)
        self.assertIn("zunit.test_case", payload["canonical"]["node_kinds"])
        self.assertIn("command_under_test", payload["canonical"]["edge_kinds"])
        self.assertEqual(
            payload["safety"],
            {
                "bounded": True,
                "raw_payloads_included": False,
                "source_snippets_included": False,
                "test_bodies_included": False,
                "expected_outputs_included": False,
                "command_strings_included": False,
                "helper_bodies_included": False,
                "fixture_contents_included": False,
                "mock_bodies_included": False,
                "secret_values_included": False,
                "path_examples_included": False,
                "zunit_executed": False,
                "zsh_executed": False,
                "shell_executed": False,
                "tests_executed": False,
                "assertions_executed": False,
                "commands_executed": False,
                "hooks_executed": False,
                "helpers_loaded": False,
                "fixtures_loaded": False,
                "mocks_applied": False,
                "stubs_applied": False,
                "filesystem_checked": False,
                "test_passed_known": False,
                "live_graph_refreshed": False,
            },
        )
        self.assertNotIn("fixtures/shell/zunit/basic.zunit", serialized)
        self.assertNotIn("ready", serialized)
        self.assertNotIn("requires network", serialized)
        for marker in FAKE_SECRET_MARKERS:
            self.assertNotIn(marker, serialized)

    def test_zunit_fixture_dogfood_prepares_existing_storage_rows(self):
        observations = fixture_observations(
            "basic.zunit",
            "hooks.zunit",
            "assertions-and-commands.zunit",
            "helpers-fixtures-mocks.zunit",
            "redaction.zunit",
        )

        prepared = prepare_canonical_load(observations)
        serialized = json.dumps(
            {
                "raw": [row.payload_json for row in prepared.raw_rows],
                "nodes": [row.metadata_json for row in prepared.canonical_rows.nodes],
                "edges": [row.metadata_json for row in prepared.canonical_rows.edges],
                "evidence": [
                    row.metadata_json for row in prepared.canonical_rows.evidence
                ],
            },
            sort_keys=True,
        )

        self.assertTrue(prepared.result.ok)
        self.assertGreater(len(prepared.raw_rows), 0)
        self.assertGreater(len(prepared.canonical_rows.nodes), 0)
        self.assertGreater(len(prepared.canonical_rows.edges), 0)
        self.assertIn(
            "zunit.test_case",
            {row.kind for row in prepared.canonical_rows.nodes},
        )
        self.assertIn(
            "command_under_test",
            {row.edge_kind for row in prepared.canonical_rows.edges},
        )
        for marker in FAKE_SECRET_MARKERS:
            self.assertNotIn(marker, serialized)

    def test_zunit_canonicalization_dogfood_does_not_invoke_subprocess_or_shells(self):
        with patch.object(subprocess, "run", side_effect=AssertionError("executed")):
            observations = fixture_observations()
            result = canonicalize_observations(observations)
            summary = summarize_zunit_evidence(observations, result)

        self.assertTrue(result.ok)
        self.assertGreater(summary.to_dict()["canonical"]["nodes"], 0)
