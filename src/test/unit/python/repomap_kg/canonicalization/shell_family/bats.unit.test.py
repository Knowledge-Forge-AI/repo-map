import json
from typing import TYPE_CHECKING
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from repomap_kg.extractors.shell.bats import extract_bats_file_observations
from repomap_kg.graph.readback.bats import summarize_bats_evidence
if TYPE_CHECKING:
    from repomap_kg.canonicalization.main import canonicalize_observations
    from repomap_kg.observations.raw import RawObservation
else:
    from repomap_kg.canonicalization import canonicalize_observations
from repomap_kg.graph.keys import (
    bats_expectation_key,
    bats_file_key,
    bats_test_case_key,
    external_key,
    file_key,
    tool_key,
)
from repomap_kg.storage import prepare_canonical_load


FIXTURE_ROOT = Path(__file__).parents[5] / "fixtures" / "shell" / "bats"
FIXTURE_NAMES = (
    "basic.bats",
    "hooks.bats",
    "helpers-and-loads.bats",
    "dynamic.bats",
    "false-positives.bats",
    "run-and-assertions.bats",
    "helpers-and-libraries.bats",
    "skip-and-fixtures.bats",
    "redaction.bats",
)
FAKE_SECRET_MARKERS = (
    "FAKE_BATS_OUTPUT_TOKEN",
    "FAKE_BATS_RUN_TOKEN",
    "FAKE_BATS_SKIP_SECRET",
    "FAKE_BATS_HELPER_TOKEN",
)


def fixture_observations(*names: str):
    observations: list[RawObservation] = []
    selected = names or FIXTURE_NAMES
    for name in selected:
        content = (FIXTURE_ROOT / name).read_text(encoding="utf-8")
        observations.extend(
            extract_bats_file_observations(f"fixtures/shell/bats/{name}", content)
        )
    return tuple(observations)


def edge_pairs(payload):
    return {
        (edge["source_key"], edge["kind"], edge["target_key"])
        for edge in payload["edges"]
    }


class BatsCanonicalizationUnitTests(unittest.TestCase):
    def test_bats_fixture_observations_create_selected_canonical_graph_evidence(self):
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
        basic_file = bats_file_key("fixtures/shell/bats/basic.bats")
        bats_file_key("fixtures/shell/bats/run-and-assertions.bats")
        helpers_file = bats_file_key("fixtures/shell/bats/helpers-and-libraries.bats")
        first_test = bats_test_case_key(
            "fixtures/shell/bats/basic.bats",
            "reports fixture status",
        )
        command_test = bats_test_case_key(
            "fixtures/shell/bats/run-and-assertions.bats",
            "records command-under-test intent",
        )
        self.assertIn(basic_file, node_keys)
        self.assertIn(first_test, node_keys)
        self.assertIn(tool_key("git"), node_keys)
        self.assertIn(external_key("bats.library", "bats-support"), node_keys)
        self.assertIn(file_key("fixtures/shell/bats/helpers/common"), node_keys)
        self.assertIn(file_key("fixtures/shell/bats/fixtures/sample.txt"), node_keys)

        pairs = edge_pairs(payload)
        self.assertIn(
            (
                file_key("fixtures/shell/bats/basic.bats"),
                "defines",
                basic_file,
            ),
            pairs,
        )
        self.assertIn((basic_file, "contains", first_test), pairs)
        self.assertIn((command_test, "tests_command", tool_key("git")), pairs)
        self.assertIn(
            (
                helpers_file,
                "depends_on",
                external_key("bats.library", "bats-support"),
            ),
            pairs,
        )
        self.assertIn(
            (
                helpers_file,
                "loads",
                file_key("fixtures/shell/bats/helpers/common"),
            ),
            pairs,
        )
        self.assertIn(
            (
                bats_test_case_key(
                    "fixtures/shell/bats/run-and-assertions.bats",
                    "checks file and directory expectations",
                ),
                "references",
                file_key("fixtures/shell/bats/fixtures/sample.txt"),
            ),
            pairs,
        )
        self.assertIn(
            (
                command_test,
                "asserts",
                bats_expectation_key(
                    "fixtures/shell/bats/run-and-assertions.bats",
                    "records command-under-test intent",
                    6,
                    "assert_success",
                ),
            ),
            pairs,
        )

    def test_dynamic_and_raw_only_bats_observations_remain_bounded(self):
        observations = fixture_observations()

        result = canonicalize_observations(observations)
        payload = result.to_dict()
        serialized = json.dumps(payload, sort_keys=True)

        self.assertTrue(result.ok)
        self.assertNotIn("tool:%24cmd", serialized)
        self.assertNotIn("tool:DYNAMIC_BATS_LIBRARY", serialized)
        self.assertNotIn("file:%5Btemp%5D", serialized)
        self.assertEqual(
            [
                diagnostic
                for diagnostic in payload["diagnostics"]
                if diagnostic["category"] == "unsupported_raw_observation_kind"
            ],
            [],
        )

        raw_evidence_kinds = {evidence["raw_kind"] for evidence in payload["evidence"]}
        self.assertTrue(
            {
                "bats.setup",
                "bats.teardown",
                "bats.output_expectation",
                "bats.status_expectation",
                "bats.skip",
                "shell.secret_like",
            }.issubset(raw_evidence_kinds)
        )
        for marker in FAKE_SECRET_MARKERS:
            self.assertNotIn(marker, serialized)

    def test_bats_fixture_dogfood_summary_is_bounded_and_count_only(self):
        observations = fixture_observations()
        result = canonicalize_observations(observations)

        summary = summarize_bats_evidence(observations, result)
        payload = summary.to_dict()
        serialized = json.dumps(payload, sort_keys=True)

        self.assertGreater(payload["raw_observations"], 0)
        self.assertGreater(payload["bats"]["files"], 0)
        self.assertGreater(payload["bats"]["test_cases"], 0)
        self.assertGreater(payload["bats"]["hooks"], 0)
        self.assertGreater(payload["bats"]["loads"], 0)
        self.assertGreater(payload["bats"]["library_loads"], 0)
        self.assertGreater(payload["bats"]["runs"], 0)
        self.assertGreater(payload["bats"]["assertions"], 0)
        self.assertGreater(payload["bats"]["refutations"], 0)
        self.assertGreater(payload["bats"]["fixture_references"], 0)
        self.assertGreater(payload["bats"]["helper_references"], 0)
        self.assertGreater(payload["bats"]["dynamic_or_unknown"], 0)
        self.assertGreater(payload["bats"]["secret_like_redacted"], 0)
        self.assertGreater(payload["canonical"]["nodes"], 0)
        self.assertGreater(payload["canonical"]["edges"], 0)
        self.assertIn("bats.test_case", payload["canonical"]["node_kinds"])
        self.assertIn("tests_command", payload["canonical"]["edge_kinds"])
        self.assertEqual(
            payload["safety"],
            {
                "bounded": True,
                "raw_payloads_included": False,
                "source_snippets_included": False,
                "expected_outputs_included": False,
                "heredoc_bodies_included": False,
                "secret_values_included": False,
                "path_examples_included": False,
                "bats_executed": False,
                "shell_executed": False,
                "commands_executed": False,
                "helpers_executed": False,
                "live_graph_refreshed": False,
            },
        )
        self.assertNotIn("fixtures/shell/bats/basic.bats", serialized)
        for marker in FAKE_SECRET_MARKERS:
            self.assertNotIn(marker, serialized)

    def test_bats_fixture_dogfood_prepares_existing_storage_rows(self):
        observations = fixture_observations(
            "basic.bats",
            "run-and-assertions.bats",
            "helpers-and-libraries.bats",
            "redaction.bats",
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
            "bats.test_case",
            {row.kind for row in prepared.canonical_rows.nodes},
        )
        self.assertIn(
            "tests_command",
            {row.edge_kind for row in prepared.canonical_rows.edges},
        )
        for marker in FAKE_SECRET_MARKERS:
            self.assertNotIn(marker, serialized)

    def test_bats_canonicalization_dogfood_does_not_invoke_subprocess_or_shells(self):
        with patch.object(subprocess, "run", side_effect=AssertionError("executed")):
            observations = fixture_observations()
            result = canonicalize_observations(observations)
            summary = summarize_bats_evidence(observations, result)

        self.assertTrue(result.ok)
        self.assertGreater(summary.to_dict()["canonical"]["nodes"], 0)


if __name__ == "__main__":
    unittest.main()
