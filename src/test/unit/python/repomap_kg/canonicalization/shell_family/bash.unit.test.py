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

from repomap_kg.extractors.shell.bash import extract_bash_file_observations
from repomap_kg.graph.keys import (
    bash_function_key,
    bash_script_key,
    env_key,
    external_url_key,
    file_key,
    host_category_key,
    tool_key,
)
from repomap_kg.graph.readback.bash import summarize_bash_evidence
from repomap_kg.storage import prepare_canonical_load


FIXTURE_ROOT = Path(__file__).parents[5] / "fixtures" / "shell" / "bash"
FIXTURE_NAMES = (
    "basic.bash",
    "functions-and-source.bash",
    "dynamic.bash",
    "redaction.env.example",
    "false-positives.bash",
    "commands-pipelines-redirects.bash",
    "heredocs.bash",
    "side-effects.bash",
    "advanced-safety.bash",
)
FAKE_SECRET_MARKERS = (
    "FAKE_BASH_PASSWORD",
    "FAKE_BASH_TOKEN",
    "FAKE_BASH_AWS_SECRET",
    "FAKE_BASH_NPM_TOKEN",
    "FAKE_BASH_API_KEY",
    "FAKE_BASH_HEADER_SECRET",
    "FAKE_BASH_HEREDOC_TOKEN",
    "FAKE_BASH_HEREDOC_PASSWORD",
    "FAKE_BASH_HEREDOC_API_KEY",
    "FAKE_BASH_SIDE_EFFECT_TOKEN",
    "FAKE_SECURITY_PASSWORD",
    "FAKE_DOCKER_PASSWORD",
    "FAKE_ALIAS_TOKEN",
    "FAKE_BASH_ARRAY_TOKEN",
    "FAKE_TRAP_TOKEN",
)


def fixture_observations(*names: str):
    observations: list[RawObservation] = []
    selected = names or FIXTURE_NAMES
    for name in selected:
        content = (FIXTURE_ROOT / name).read_text(encoding="utf-8")
        observations.extend(
            extract_bash_file_observations(f"fixtures/shell/bash/{name}", content)
        )
    return tuple(observations)


def edge_pairs(payload):
    return {
        (edge["source_key"], edge["kind"], edge["target_key"])
        for edge in payload["edges"]
    }


class BashCanonicalizationUnitTests(unittest.TestCase):
    def test_bash_fixture_observations_create_selected_canonical_graph_evidence(self):
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
        self.assertIn(
            bash_script_key("fixtures/shell/bash/basic.bash"),
            node_keys,
        )
        self.assertIn(
            bash_function_key("fixtures/shell/bash/basic.bash", "build_report"),
            node_keys,
        )
        self.assertIn(tool_key("git"), node_keys)
        self.assertIn(tool_key("curl"), node_keys)
        self.assertIn(env_key("EXAMPLE_TOKEN"), node_keys)
        self.assertIn(host_category_key("file-write"), node_keys)
        self.assertIn(host_category_key("package-management"), node_keys)
        self.assertIn(external_url_key("https://example.invalid/archive.tar.gz"), node_keys)

        pairs = edge_pairs(payload)
        script_key = bash_script_key("fixtures/shell/bash/basic.bash")
        self.assertIn(
            (
                file_key("fixtures/shell/bash/basic.bash"),
                "defines",
                script_key,
            ),
            pairs,
        )
        self.assertIn(
            (
                script_key,
                "defines",
                bash_function_key("fixtures/shell/bash/basic.bash", "build_report"),
            ),
            pairs,
        )
        self.assertIn(
            (
                bash_script_key("fixtures/shell/bash/functions-and-source.bash"),
                "sources",
                file_key("fixtures/shell/bash/lib/common.bash"),
            ),
            pairs,
        )
        self.assertIn(
            (
                file_key("fixtures/shell/bash/commands-pipelines-redirects.bash"),
                "executes",
                tool_key("git"),
            ),
            pairs,
        )
        self.assertIn(
            (
                file_key("fixtures/shell/bash/side-effects.bash"),
                "writes_env",
                env_key("EXAMPLE_TOKEN"),
            ),
            pairs,
        )
        self.assertIn(
            (
                file_key("fixtures/shell/bash/side-effects.bash"),
                "mutates_host",
                host_category_key("package-management"),
            ),
            pairs,
        )

    def test_dynamic_and_raw_only_bash_observations_remain_bounded(self):
        observations = fixture_observations()

        result = canonicalize_observations(observations)
        payload = result.to_dict()
        serialized = json.dumps(payload, sort_keys=True)

        self.assertTrue(result.ok)
        self.assertNotIn("tool:DYNAMIC_COMMAND", serialized)
        self.assertNotIn("tool:COMMAND_NAME", serialized)
        self.assertNotIn("file:%24COMPUTED_SOURCE", serialized)
        self.assertNotIn("dynamic:tool:bash-c", serialized)
        self.assertEqual(
            [
                diagnostic
                for diagnostic in payload["diagnostics"]
                if diagnostic["category"] == "unsupported_raw_observation_kind"
            ],
            [],
        )

        raw_evidence_kinds = {
            evidence["raw_kind"] for evidence in payload["evidence"]
        }
        self.assertTrue(
            {
                "bash.alias",
                "bash.array_assignment",
                "bash.trap",
                "shell.dynamic_invocation",
                "shell.heredoc",
                "shell.pipeline",
                "shell.command_argument",
            }.issubset(raw_evidence_kinds)
        )
        for marker in FAKE_SECRET_MARKERS:
            self.assertNotIn(marker, serialized)

    def test_bash_fixture_dogfood_summary_is_bounded_and_count_only(self):
        observations = fixture_observations()
        result = canonicalize_observations(observations)

        summary = summarize_bash_evidence(observations, result)
        payload = summary.to_dict()
        serialized = json.dumps(payload, sort_keys=True)

        self.assertGreater(payload["raw_observations"], 0)
        self.assertGreater(payload["bash"]["files"], 0)
        self.assertGreater(payload["bash"]["functions"], 0)
        self.assertGreater(payload["bash"]["commands"], 0)
        self.assertGreater(payload["bash"]["external_commands"], 0)
        self.assertGreater(payload["bash"]["host_mutations"], 0)
        self.assertGreater(payload["bash"]["aliases"], 0)
        self.assertGreater(payload["bash"]["array_assignments"], 0)
        self.assertGreater(payload["bash"]["traps"], 0)
        self.assertGreater(payload["canonical"]["nodes"], 0)
        self.assertGreater(payload["canonical"]["edges"], 0)
        self.assertIn("bash.function", payload["canonical"]["node_kinds"])
        self.assertIn("executes", payload["canonical"]["edge_kinds"])
        self.assertEqual(
            payload["safety"],
            {
                "bounded": True,
                "raw_payloads_included": False,
                "path_examples_included": False,
                "source_snippets_included": False,
                "heredoc_bodies_included": False,
                "trap_bodies_included": False,
                "secret_values_included": False,
                "shell_executed": False,
                "live_graph_refreshed": False,
            },
        )
        self.assertNotIn("fixtures/shell/bash/basic.bash", serialized)
        for marker in FAKE_SECRET_MARKERS:
            self.assertNotIn(marker, serialized)

    def test_bash_fixture_dogfood_prepares_existing_storage_rows(self):
        observations = fixture_observations(
            "basic.bash",
            "commands-pipelines-redirects.bash",
            "side-effects.bash",
            "advanced-safety.bash",
        )

        prepared = prepare_canonical_load(observations)
        serialized = json.dumps(
            {
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
            "bash.function",
            {row.kind for row in prepared.canonical_rows.nodes},
        )
        self.assertIn(
            "mutates_host",
            {row.edge_kind for row in prepared.canonical_rows.edges},
        )
        for marker in FAKE_SECRET_MARKERS:
            self.assertNotIn(marker, serialized)

    def test_bash_canonicalization_dogfood_does_not_invoke_subprocess_or_shells(self):
        with patch.object(subprocess, "run", side_effect=AssertionError("executed")):
            observations = fixture_observations()
            result = canonicalize_observations(observations)
            summary = summarize_bash_evidence(observations, result)

        self.assertTrue(result.ok)
        self.assertGreater(summary.to_dict()["canonical"]["nodes"], 0)


if __name__ == "__main__":
    unittest.main()
