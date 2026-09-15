import unittest

from repomap_kg.canonicalization.main import (
    canonicalize_observations,
)
from repomap_kg.observations.raw import RawObservation


class CanonicalizationNixFamilyContractsUnitTests(unittest.TestCase):
    def test_nix_import_creates_sources_edge(self):
        observation = RawObservation(
            kind="nix.import",
            source_id="flake.nix#nix-import:2:modules-one-nix",
            path="flake.nix",
            start_line=2,
            end_line=2,
            target="file:modules/one.nix",
            confidence="heuristic",
            extractor="repo-nix",
            extractor_version="0.1.0",
            metadata={
                "import_path": "./modules/one.nix",
                "resolved_path": "modules/one.nix",
                "resolution": "local",
                "syntax": "imports-list",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(
            [(node["canonical_key"], node["kind"]) for node in payload["nodes"]],
            [
                ("file:flake.nix", "file"),
                ("file:modules/one.nix", "file"),
            ],
        )
        self.assertEqual(payload["edges"][0]["source_key"], "file:flake.nix")
        self.assertEqual(payload["edges"][0]["kind"], "sources")
        self.assertEqual(payload["edges"][0]["target_key"], "file:modules/one.nix")
        self.assertEqual(payload["edges"][0]["metadata"]["resolved_paths"], [
            "modules/one.nix",
        ])

    def test_nix_app_defines_output_and_exposes_static_program_path(self):
        observation = RawObservation(
            kind="nix.app",
            source_id="flake.nix#nix-app:aarch64-darwin:tool",
            path="flake.nix",
            start_line=4,
            end_line=7,
            name="tool",
            target="nix.app:repo-map:aarch64-darwin:tool",
            confidence="heuristic",
            extractor="repo-nix",
            extractor_version="0.1.0",
            metadata={
                "flake_ref": "repo-map",
                "system": "aarch64-darwin",
                "name": "tool",
                "app": "tool",
                "attr_path": "apps.aarch64-darwin.tool",
                "output_kind": "app",
                "program": "\"${self}/bin/tool\"",
                "program_path": "bin/tool",
                "program_resolution": "local",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(
            [edge["kind"] for edge in payload["edges"]],
            ["defines", "exposes_script"],
        )
        self.assertEqual(
            [(edge["source_key"], edge["target_key"]) for edge in payload["edges"]],
            [
                ("file:flake.nix", "nix.app:repo-map:aarch64-darwin:tool"),
                ("nix.app:repo-map:aarch64-darwin:tool", "file:bin/tool"),
            ],
        )
        self.assertEqual(payload["edges"][1]["metadata"]["program_paths"], [
            "bin/tool",
        ])
        self.assertEqual(payload["summary"]["edge_evidence_links"], 2)

    def test_nix_outputs_create_defines_edges(self):
        observations = [
            RawObservation(
                kind=kind,
                source_id=f"flake.nix#nix-{raw_slug}:aarch64-darwin:{name}",
                path="flake.nix",
                start_line=line,
                end_line=line,
                name=name,
                target=target,
                confidence="heuristic",
                extractor="repo-nix",
                extractor_version="0.1.0",
                metadata={
                    "flake_ref": "repo-map",
                    "system": "aarch64-darwin",
                    "name": name,
                    "attr_path": attr_path,
                    "output_kind": output_kind,
                },
            )
            for kind, raw_slug, output_kind, name, target, attr_path, line in (
                (
                    "nix.package",
                    "package",
                    "package",
                    "default",
                    "nix.package:repo-map:aarch64-darwin:default",
                    "packages.aarch64-darwin.default",
                    2,
                ),
                (
                    "nix.devShell",
                    "devShell",
                    "devShell",
                    "default",
                    "nix.devShell:repo-map:aarch64-darwin:default",
                    "devShells.aarch64-darwin.default",
                    3,
                ),
                (
                    "nix.check",
                    "check",
                    "check",
                    "unit",
                    "nix.check:repo-map:aarch64-darwin:unit",
                    "checks.aarch64-darwin.unit",
                    4,
                ),
            )
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual([edge["kind"] for edge in payload["edges"]], [
            "defines",
            "defines",
            "defines",
        ])
        self.assertEqual(
            [edge["target_key"] for edge in payload["edges"]],
            [
                "nix.check:repo-map:aarch64-darwin:unit",
                "nix.devShell:repo-map:aarch64-darwin:default",
                "nix.package:repo-map:aarch64-darwin:default",
            ],
        )

    def test_nix_path_ref_remains_raw_only_until_supported_edge_exists(self):
        observation = RawObservation(
            kind="nix.path_ref",
            source_id="flake.nix#nix-path:2:bin-tool",
            path="flake.nix",
            start_line=2,
            end_line=2,
            target="file:bin/tool",
            confidence="heuristic",
            extractor="repo-nix",
            extractor_version="0.1.0",
            metadata={
                "path_ref": "./bin/tool",
                "resolved_path": "bin/tool",
                "resolution": "local",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["nodes"], 0)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(
            payload["diagnostics"][0]["category"],
            "unsupported_raw_observation_kind",
        )


if __name__ == "__main__":
    unittest.main()
