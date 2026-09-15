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

from repomap_kg.extractors.shell.awk import extract_awk_file_observations
from repomap_kg.graph.readback.awk import summarize_awk_evidence
from repomap_kg.graph.keys import (
    awk_function_key,
    awk_program_key,
    external_key,
    file_key,
)
from repomap_kg.storage import prepare_canonical_load


FIXTURE_ROOT = Path(__file__).parents[5] / "fixtures" / "shell" / "awk"
FIXTURE_NAMES = (
    "basic.awk",
    "patterns-and-actions.awk",
    "functions.awk",
    "dynamic.awk",
    "redaction.awk",
    "gawk-extensions.awk",
    "false-positives.awk",
    "io-and-pipes.awk",
    "calls.awk",
    "includes-and-extensions.awk",
)
FAKE_SECRET_MARKERS = (
    "FAKE_AWK_TOKEN_VALUE",
    "FAKE_AWK_PASSWORD_VALUE",
    "FAKE_AWK_SYSTEM_TOKEN",
    "FAKE_AWK_PATH_TOKEN",
)


def fixture_observations(*names: str):
    observations: list[RawObservation] = []
    selected = names or FIXTURE_NAMES
    for name in selected:
        content = (FIXTURE_ROOT / name).read_text(encoding="utf-8")
        observations.extend(
            extract_awk_file_observations(f"fixtures/shell/awk/{name}", content)
        )
    return tuple(observations)


def edge_pairs(payload):
    return {
        (edge["source_key"], edge["kind"], edge["target_key"])
        for edge in payload["edges"]
    }


class AwkCanonicalizationUnitTests(unittest.TestCase):
    def test_awk_fixture_observations_create_selected_canonical_graph_evidence(self):
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

        basic_program = awk_program_key("fixtures/shell/awk/basic.awk")
        functions_program = awk_program_key("fixtures/shell/awk/functions.awk")
        calls_program = awk_program_key("fixtures/shell/awk/calls.awk")
        io_program = awk_program_key("fixtures/shell/awk/io-and-pipes.awk")
        includes_program = awk_program_key(
            "fixtures/shell/awk/includes-and-extensions.awk"
        )
        normalize_function = awk_function_key(
            "fixtures/shell/awk/functions.awk",
            "normalize",
        )
        calls_normalize_function = awk_function_key(
            "fixtures/shell/awk/calls.awk",
            "normalize",
        )

        node_keys = {node["canonical_key"] for node in payload["nodes"]}
        self.assertIn(basic_program, node_keys)
        self.assertIn(normalize_function, node_keys)
        self.assertIn(calls_normalize_function, node_keys)
        self.assertIn(external_key("awk.builtin", "print"), node_keys)
        self.assertIn(external_key("awk.extension", "ordchr"), node_keys)
        self.assertIn(file_key("fixtures/shell/awk/lib/common.awk"), node_keys)
        self.assertIn(
            file_key("fixtures/shell/awk/docs/examples/awk/public-input.txt"),
            node_keys,
        )
        self.assertIn(
            external_key("awk.command_intent", "printf static-example"),
            node_keys,
        )

        pairs = edge_pairs(payload)
        self.assertIn(
            (
                file_key("fixtures/shell/awk/basic.awk"),
                "defines",
                basic_program,
            ),
            pairs,
        )
        self.assertIn(
            (
                functions_program,
                "defines",
                normalize_function,
            ),
            pairs,
        )
        self.assertIn(
            (
                calls_program,
                "calls",
                calls_normalize_function,
            ),
            pairs,
        )
        self.assertIn(
            (
                calls_program,
                "uses_builtin",
                external_key("awk.builtin", "print"),
            ),
            pairs,
        )
        self.assertIn(
            (
                includes_program,
                "includes",
                file_key("fixtures/shell/awk/lib/common.awk"),
            ),
            pairs,
        )
        self.assertIn(
            (
                includes_program,
                "depends_on",
                external_key("awk.extension", "ordchr"),
            ),
            pairs,
        )
        self.assertIn(
            (
                io_program,
                "reads",
                file_key("fixtures/shell/awk/docs/examples/awk/public-input.txt"),
            ),
            pairs,
        )
        self.assertIn(
            (
                io_program,
                "writes",
                file_key("fixtures/shell/awk/docs/examples/awk/public-output.txt"),
            ),
            pairs,
        )
        self.assertIn(
            (
                io_program,
                "system_command_intent",
                external_key("awk.command_intent", "printf static-example"),
            ),
            pairs,
        )

        edge_payloads = {
            (edge["source_key"], edge["kind"], edge["target_key"]): edge
            for edge in payload["edges"]
        }
        system_edge = edge_payloads[
            (
                io_program,
                "system_command_intent",
                external_key("awk.command_intent", "printf static-example"),
            )
        ]
        self.assertTrue(system_edge["metadata"]["runtime_intent"])
        self.assertFalse(system_edge["metadata"]["command_executed"])
        self.assertFalse(system_edge["metadata"]["awk_executed"])
        self.assertFalse(system_edge["metadata"]["shell_executed"])
        self.assertFalse(system_edge["metadata"]["host_mutation_proven"])
        self.assertNotIn("mutates_host", {edge["kind"] for edge in payload["edges"]})
        self.assertNotIn("host.category", {node["kind"] for node in payload["nodes"]})

    def test_dynamic_and_raw_only_awk_observations_remain_bounded(self):
        observations = fixture_observations()

        result = canonicalize_observations(observations)
        payload = result.to_dict()
        serialized = json.dumps(payload, sort_keys=True)

        self.assertTrue(result.ok)
        self.assertNotIn("external:awk.command_intent:%5Bdynamic%5D", serialized)
        self.assertNotIn("file:%5Bdynamic%5D", serialized)
        self.assertNotIn("file:%24", serialized)
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
                "awk.begin",
                "awk.end",
                "awk.pattern_action",
                "awk.variable_assignment",
                "awk.field_reference",
                "awk.record_reference",
                "awk.dynamic_expression",
                "awk.redirect",
                "awk.secret_like",
            }.issubset(raw_evidence_kinds)
        )
        for marker in FAKE_SECRET_MARKERS:
            self.assertNotIn(marker, serialized)

    def test_awk_fixture_dogfood_summary_is_bounded_and_count_only(self):
        observations = fixture_observations()
        result = canonicalize_observations(observations)

        summary = summarize_awk_evidence(observations, result)
        payload = summary.to_dict()
        serialized = json.dumps(payload, sort_keys=True)

        self.assertGreater(payload["raw_observations"], 0)
        self.assertGreater(payload["awk"]["programs"], 0)
        self.assertGreater(payload["awk"]["begins"], 0)
        self.assertGreater(payload["awk"]["ends"], 0)
        self.assertGreater(payload["awk"]["pattern_actions"], 0)
        self.assertGreater(payload["awk"]["functions"], 0)
        self.assertGreater(payload["awk"]["variable_assignments"], 0)
        self.assertGreater(payload["awk"]["field_references"], 0)
        self.assertGreater(payload["awk"]["record_references"], 0)
        self.assertGreater(payload["awk"]["builtin_calls"], 0)
        self.assertGreater(payload["awk"]["user_function_calls"], 0)
        self.assertGreater(payload["awk"]["file_reads"], 0)
        self.assertGreater(payload["awk"]["file_writes"], 0)
        self.assertGreater(payload["awk"]["pipe_reads"], 0)
        self.assertGreater(payload["awk"]["pipe_writes"], 0)
        self.assertGreater(payload["awk"]["system_calls"], 0)
        self.assertGreater(payload["awk"]["redirects"], 0)
        self.assertGreater(payload["awk"]["includes"], 0)
        self.assertGreater(payload["awk"]["extensions"], 0)
        self.assertGreater(payload["awk"]["dynamic_or_unknown"], 0)
        self.assertGreater(payload["awk"]["secret_like_redacted"], 0)
        self.assertGreater(payload["canonical"]["nodes"], 0)
        self.assertGreater(payload["canonical"]["edges"], 0)
        self.assertIn("awk.program", payload["canonical"]["node_kinds"])
        self.assertIn("system_command_intent", payload["canonical"]["edge_kinds"])
        self.assertEqual(
            payload["safety"],
            {
                "bounded": True,
                "raw_payloads_included": False,
                "source_snippets_included": False,
                "command_strings_included": False,
                "secret_values_included": False,
                "path_examples_included": False,
                "awk_executed": False,
                "shell_executed": False,
                "commands_executed": False,
                "files_opened": False,
                "filesystem_checked": False,
                "host_mutation_proven": False,
                "live_graph_refreshed": False,
            },
        )
        self.assertNotIn("fixtures/shell/awk/basic.awk", serialized)
        self.assertNotIn("printf static-example", serialized)
        for marker in FAKE_SECRET_MARKERS:
            self.assertNotIn(marker, serialized)

    def test_awk_fixture_dogfood_prepares_existing_storage_rows(self):
        observations = fixture_observations(
            "basic.awk",
            "functions.awk",
            "calls.awk",
            "io-and-pipes.awk",
            "includes-and-extensions.awk",
            "redaction.awk",
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
            "awk.program",
            {row.kind for row in prepared.canonical_rows.nodes},
        )
        self.assertIn(
            "awk.function",
            {row.kind for row in prepared.canonical_rows.nodes},
        )
        self.assertIn(
            "system_command_intent",
            {row.edge_kind for row in prepared.canonical_rows.edges},
        )
        self.assertNotIn(
            "mutates_host",
            {row.edge_kind for row in prepared.canonical_rows.edges},
        )
        for marker in FAKE_SECRET_MARKERS:
            self.assertNotIn(marker, serialized)

    def test_awk_canonicalization_dogfood_does_not_invoke_subprocess_or_shells(self):
        with patch.object(subprocess, "run", side_effect=AssertionError("executed")):
            observations = fixture_observations()
            result = canonicalize_observations(observations)
            summary = summarize_awk_evidence(observations, result)

        self.assertTrue(result.ok)
        self.assertGreater(summary.to_dict()["canonical"]["nodes"], 0)


if __name__ == "__main__":
    unittest.main()
