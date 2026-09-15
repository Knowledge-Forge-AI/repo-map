import json
import unittest
from collections import Counter

from repomap_kg.graph.keys import (
    nix_output_key,
)

from repomap_test_support.canonicalization import (
    canonicalize_fixture_payload,
    expected_graph_fixture,
    raw_fixture_records,
)


class CanonicalizationNixFamilyUnitTests(unittest.TestCase):
    def test_nix_summary1_flake_fixture_raw_observation_counts_are_characterized(self):
        records = raw_fixture_records("nix_flake_basic")
        raw_counts = Counter(record["kind"] for record in records)

        self.assertEqual(
            raw_counts,
            Counter(
                {
                    "file": 3,
                    "nix.import": 1,
                    "nix.path_ref": 1,
                    "nix.app": 1,
                    "nix.package": 1,
                    "nix.devShell": 1,
                    "nix.check": 1,
                }
            ),
        )
        self.assertEqual(
            {
                record["kind"]
                for record in records
                if record["kind"].startswith("nix.")
            },
            {
                "nix.import",
                "nix.path_ref",
                "nix.app",
                "nix.package",
                "nix.devShell",
                "nix.check",
            },
        )

    def test_nix_summary1_flake_fixture_canonical_node_counts_are_characterized(self):
        graph = expected_graph_fixture("nix_flake_basic")
        node_counts = Counter(node["kind"] for node in graph["nodes"])

        self.assertEqual(
            node_counts,
            Counter(
                {
                    "file": 3,
                    "nix.app": 1,
                    "nix.package": 1,
                    "nix.devShell": 1,
                    "nix.check": 1,
                }
            ),
        )
        self.assertEqual(
            {
                node["canonical_key"]
                for node in graph["nodes"]
                if node["kind"].startswith("nix.")
            },
            {
                "nix.app:repo-map:aarch64-darwin:tool",
                "nix.package:repo-map:aarch64-darwin:default",
                "nix.devShell:repo-map:aarch64-darwin:default",
                "nix.check:repo-map:aarch64-darwin:unit",
            },
        )
        self.assertNotIn("nix.path_ref", node_counts)
        self.assertFalse(
            any(
                node["canonical_key"].startswith("nix.path_ref:")
                for node in graph["nodes"]
            )
        )

    def test_nix_summary1_flake_fixture_canonical_edge_counts_are_characterized(self):
        graph = expected_graph_fixture("nix_flake_basic")
        edge_counts = Counter(edge["kind"] for edge in graph["edges"])
        edge_triples = {
            (edge["source_key"], edge["kind"], edge["target_key"])
            for edge in graph["edges"]
        }

        self.assertEqual(
            edge_counts,
            Counter({"defines": 4, "sources": 1, "exposes_script": 1}),
        )
        self.assertEqual(
            {
                target_key
                for source_key, kind, target_key in edge_triples
                if source_key == "file:flake.nix" and kind == "defines"
            },
            {
                "nix.app:repo-map:aarch64-darwin:tool",
                "nix.package:repo-map:aarch64-darwin:default",
                "nix.devShell:repo-map:aarch64-darwin:default",
                "nix.check:repo-map:aarch64-darwin:unit",
            },
        )
        self.assertIn(
            ("file:flake.nix", "sources", "file:modules/base.nix"),
            edge_triples,
        )
        self.assertIn(
            (
                "nix.app:repo-map:aarch64-darwin:tool",
                "exposes_script",
                "file:bin/tool",
            ),
            edge_triples,
        )

    def test_nix_summary1_path_refs_remain_raw_only(self):
        records = raw_fixture_records("nix_flake_basic")
        graph = expected_graph_fixture("nix_flake_basic")
        path_refs = [record for record in records if record["kind"] == "nix.path_ref"]
        graph_keys = {node["canonical_key"] for node in graph["nodes"]}
        edge_keys = {
            key
            for edge in graph["edges"]
            for key in (edge["source_key"], edge["target_key"])
        }

        self.assertEqual(len(path_refs), 1)
        self.assertEqual(path_refs[0]["target"], "file:config/settings.json")
        self.assertEqual(path_refs[0]["metadata"]["resolution"], "local")
        self.assertNotIn("file:config/settings.json", graph_keys)
        self.assertNotIn("file:config/settings.json", edge_keys)

    def test_nix_summary1_config_evidence_counts_are_characterized(self):
        records = raw_fixture_records("yaml_basic")
        graph = expected_graph_fixture("yaml_basic")
        raw_counts = Counter(record["kind"] for record in records)
        node_counts = Counter(node["kind"] for node in graph["nodes"])
        edge_counts = Counter(edge["kind"] for edge in graph["edges"])

        self.assertEqual(raw_counts["config.document"], 17)
        self.assertEqual(raw_counts["config.path"], 153)
        self.assertEqual(raw_counts["config.reference"], 21)
        self.assertEqual(raw_counts["config.parse_error"], 2)
        self.assertEqual(node_counts["config.document"], 17)
        self.assertEqual(node_counts["config.path"], 153)
        self.assertEqual(edge_counts["references"], 21)
        self.assertEqual(edge_counts["defines"], 170)
        self.assertEqual(
            edge_counts["defines"],
            node_counts["config.document"] + node_counts["config.path"],
        )

    def test_nix_canon1_output_sections_expected_as_weak_output_nodes(self):
        payload = canonicalize_fixture_payload("nix_output_sections_basic")
        output_nodes = {
            node["canonical_key"]: node
            for node in payload["nodes"]
            if node["kind"] == "nix.output"
        }
        expected_keys = {
            nix_output_key("file:flake.nix", "section/packages"),
            nix_output_key("file:flake.nix", "section/checks"),
            nix_output_key("file:flake.nix", "section/legacyPackages"),
        }

        self.assertEqual(set(output_nodes), expected_keys)
        self.assertEqual(
            {
                node["metadata"]["section"]
                for node in output_nodes.values()
            },
            {"packages", "checks", "legacyPackages"},
        )
        self.assertTrue(
            all(
                node["metadata"]["identity_precision"] == "section_category"
                for node in output_nodes.values()
            )
        )
        self.assertTrue(
            all(
                node["metadata"]["concrete_output_identity"] is False
                for node in output_nodes.values()
            )
        )

    def test_nix_canon1_output_sections_expected_defines_edges(self):
        payload = canonicalize_fixture_payload("nix_output_sections_basic")
        expected_targets = {
            nix_output_key("file:flake.nix", "section/packages"),
            nix_output_key("file:flake.nix", "section/checks"),
            nix_output_key("file:flake.nix", "section/legacyPackages"),
        }
        actual_targets = {
            edge["target_key"]
            for edge in payload["edges"]
            if edge["source_key"] == "file:flake.nix" and edge["kind"] == "defines"
        }

        self.assertEqual(actual_targets, expected_targets)

    def test_nix_canon1_section_evidence_does_not_fabricate_concrete_outputs(self):
        payload = canonicalize_fixture_payload("nix_output_sections_basic")
        node_counts = Counter(node["kind"] for node in payload["nodes"])
        edge_triples = {
            (edge["source_key"], edge["kind"], edge["target_key"])
            for edge in payload["edges"]
        }

        for concrete_kind in (
            "nix.app",
            "nix.package",
            "nix.devShell",
            "nix.check",
        ):
            self.assertEqual(node_counts[concrete_kind], 0)
        self.assertFalse(
            any(
                target_key.startswith(
                    (
                        "nix.app:",
                        "nix.package:",
                        "nix.devShell:",
                        "nix.check:",
                    )
                )
                for _, _, target_key in edge_triples
            )
        )

    def test_nix_canon1_inputs_and_diagnostics_remain_raw_only(self):
        payload = canonicalize_fixture_payload("nix_output_sections_basic")
        raw_only_kinds = {
            "nix.flake_input",
            "nix.dynamic_output_shape",
            "nix.unsupported_flake_shape",
            "nix.path_ref",
        }
        node_kinds = {node["kind"] for node in payload["nodes"]}
        edge_payload = json.dumps(payload["edges"], sort_keys=True)
        unsupported_values = {
            diagnostic["value"]
            for diagnostic in payload["diagnostics"]
            if diagnostic["category"] == "unsupported_raw_observation_kind"
        }

        self.assertTrue(raw_only_kinds.issubset(unsupported_values))
        self.assertTrue(raw_only_kinds.isdisjoint(node_kinds))
        for raw_only_kind in raw_only_kinds:
            self.assertNotIn(raw_only_kind, edge_payload)

    def test_nix_canon1_expected_payload_is_public_safe(self):
        records = raw_fixture_records("nix_output_sections_basic")
        payload = canonicalize_fixture_payload("nix_output_sections_basic")
        serialized = json.dumps(
            {"canonical": payload, "raw": records},
            sort_keys=True,
        )

        for forbidden in (
            "/users/",
            "/home/",
            "http://",
            "https://",
            "ssh://",
            "git@",
            "github:",
            "token",
            "secret",
            "password",
            "api_key",
            "command",
            "snippet",
            "raw_expression",
            "source_value",
            "config/settings",
            "./",
        ):
            self.assertNotIn(forbidden, serialized.lower())



if __name__ == "__main__":
    unittest.main()
