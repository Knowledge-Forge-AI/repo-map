import json
import unittest
from pathlib import Path

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repomap_kg.canonicalization.main import canonicalize_observations
    from repomap_kg.observations.raw import RawObservation
else:
    from repomap_kg.canonicalization import canonicalize_observations
from repomap_kg.graph.keys import (
    external_key,
    file_key,
    host_category_key,
    powershell_function_key,
    powershell_manifest_export_key,
    powershell_manifest_key,
    powershell_module_key,
    powershell_script_key,
    tool_key,
)
from repomap_kg.extractors.shell.powershell import extract_powershell_file_observations
from repomap_kg.graph.readback.powershell import summarize_powershell_evidence
from repomap_kg.storage import prepare_canonical_load


FIXTURE_ROOT = Path(__file__).parents[5] / "fixtures" / "powershell"
FAKE_SECRET_MARKERS = (
    "FAKE_TOKEN_VALUE",
    "FAKE_ARG_SECRET",
    "FAKE_INLINE_SECRET",
    "FAKE_PIPELINE_SECRET",
    "FAKE_ENV_TOKEN",
    "FAKE_NET_TOKEN",
    "FAKE_API_KEY",
    "FAKE_PASSWORD",
    "FAKE_MANIFEST_TOKEN",
    "FAKE_MANIFEST_API_KEY",
    "FAKE_MANIFEST_PASSWORD",
    "fake-manifest-pat",
    "Bearer FAKE_MANIFEST_AUTH",
    "FAKE_SPLAT_TOKEN",
)


def fixture_observations(*names: str):
    observations: list[RawObservation] = []
    for name in names:
        content = (FIXTURE_ROOT / name).read_text(encoding="utf-8")
        observations.extend(
            extract_powershell_file_observations(f"fixtures/powershell/{name}", content)
        )
    return tuple(observations)


def edge_pairs(payload):
    return {
        (edge["source_key"], edge["kind"], edge["target_key"])
        for edge in payload["edges"]
    }


class PowerShellCanonicalizationUnitTests(unittest.TestCase):
    def test_structural_and_command_observations_create_canonical_graph_evidence(self):
        observations = fixture_observations(
            "basic-script.ps1",
            "Example.Module.psm1",
            "Advanced.Module.psd1",
            "commands-and-pipelines.ps1",
            "side-effects.ps1",
        )

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertNotIn(
            "unsupported_raw_observation_kind",
            {diagnostic["category"] for diagnostic in payload["diagnostics"]},
        )
        self.assertIn(
            powershell_script_key("fixtures/powershell/basic-script.ps1"),
            {node["canonical_key"] for node in payload["nodes"]},
        )
        self.assertIn(
            powershell_module_key("fixtures/powershell/Example.Module.psm1"),
            {node["canonical_key"] for node in payload["nodes"]},
        )
        self.assertIn(
            powershell_manifest_key("fixtures/powershell/Advanced.Module.psd1"),
            {node["canonical_key"] for node in payload["nodes"]},
        )
        self.assertIn(
            powershell_function_key(
                "fixtures/powershell/basic-script.ps1",
                "Invoke-ExampleMaintenance",
            ),
            {node["canonical_key"] for node in payload["nodes"]},
        )
        self.assertIn(
            tool_key("Get-ChildItem"),
            {node["canonical_key"] for node in payload["nodes"]},
        )
        self.assertIn(
            host_category_key("file-write"),
            {node["canonical_key"] for node in payload["nodes"]},
        )

        pairs = edge_pairs(payload)
        script_key = powershell_script_key("fixtures/powershell/basic-script.ps1")
        manifest_key = powershell_manifest_key("fixtures/powershell/Advanced.Module.psd1")
        self.assertIn(
            (
                file_key("fixtures/powershell/basic-script.ps1"),
                "defines",
                script_key,
            ),
            pairs,
        )
        self.assertIn(
            (
                script_key,
                "defines",
                powershell_function_key(
                    "fixtures/powershell/basic-script.ps1",
                    "Invoke-ExampleMaintenance",
                ),
            ),
            pairs,
        )
        self.assertIn(
            (
                script_key,
                "imports",
                external_key("powershell.module", "Microsoft.PowerShell.Management"),
            ),
            pairs,
        )
        self.assertIn(
            (
                script_key,
                "sources",
                file_key("fixtures/powershell/helpers/Example.Shared.ps1"),
            ),
            pairs,
        )
        self.assertIn(
            (
                file_key("fixtures/powershell/commands-and-pipelines.ps1"),
                "executes",
                tool_key("Get-ChildItem"),
            ),
            pairs,
        )
        self.assertIn(
            (
                manifest_key,
                "depends_on",
                external_key("powershell.module", "ThreadJob"),
            ),
            pairs,
        )
        self.assertIn(
            (
                manifest_key,
                "references",
                file_key("fixtures/powershell/Advanced.Module.psm1"),
            ),
            pairs,
        )
        self.assertIn(
            (
                manifest_key,
                "defines",
                powershell_manifest_export_key(
                    manifest_key,
                    "function",
                    "Get-AdvancedThing",
                ),
            ),
            pairs,
        )

    def test_dynamic_invocation_and_secret_markers_remain_bounded(self):
        observations = fixture_observations(
            "dynamic-and-secrets.ps1",
            "aliases-splats-dynamic.ps1",
            "Advanced.Module.psd1",
        )

        result = canonicalize_observations(observations)
        payload = result.to_dict()
        serialized = json.dumps(payload, sort_keys=True)

        self.assertTrue(result.ok)
        self.assertNotIn("dynamic:tool:call-operator", serialized)
        self.assertNotIn("$Command", {
            edge["target_key"] for edge in payload["edges"]
        })
        self.assertEqual(
            [
                diagnostic
                for diagnostic in payload["diagnostics"]
                if diagnostic["category"] == "unsupported_raw_observation_kind"
            ],
            [],
        )
        for marker in FAKE_SECRET_MARKERS:
            self.assertNotIn(marker, serialized)

    def test_power_shell_fixture_dogfood_summary_is_bounded_and_count_only(self):
        observations = fixture_observations(
            "basic-script.ps1",
            "Example.Module.psm1",
            "Advanced.Module.psd1",
            "commands-and-pipelines.ps1",
            "side-effects.ps1",
            "aliases-splats-dynamic.ps1",
        )
        result = canonicalize_observations(observations)

        summary = summarize_powershell_evidence(observations, result)
        payload = summary.to_dict()
        serialized = json.dumps(payload, sort_keys=True)

        self.assertGreater(payload["raw_observations"], 0)
        self.assertGreater(payload["power_shell"]["functions"], 0)
        self.assertGreater(payload["power_shell"]["commands"], 0)
        self.assertGreater(payload["power_shell"]["host_mutations"], 0)
        self.assertGreater(payload["power_shell"]["manifest_dependencies"], 0)
        self.assertGreater(payload["canonical"]["nodes"], 0)
        self.assertGreater(payload["canonical"]["edges"], 0)
        self.assertIn("powershell.function", payload["canonical"]["node_kinds"])
        self.assertIn("executes", payload["canonical"]["edge_kinds"])
        self.assertEqual(
            payload["safety"],
            {
                "bounded": True,
                "raw_payloads_included": False,
                "path_examples_included": False,
                "source_snippets_included": False,
                "powershell_executed": False,
                "secret_values_included": False,
            },
        )
        self.assertNotIn("fixtures/powershell/basic-script.ps1", serialized)
        for marker in FAKE_SECRET_MARKERS:
            self.assertNotIn(marker, serialized)

    def test_power_shell_fixture_dogfood_prepares_existing_storage_rows(self):
        observations = fixture_observations(
            "basic-script.ps1",
            "Advanced.Module.psd1",
            "commands-and-pipelines.ps1",
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
            "powershell.function",
            {row.kind for row in prepared.canonical_rows.nodes},
        )
        self.assertIn(
            "executes",
            {row.edge_kind for row in prepared.canonical_rows.edges},
        )
        for marker in FAKE_SECRET_MARKERS:
            self.assertNotIn(marker, serialized)


if __name__ == "__main__":
    unittest.main()
