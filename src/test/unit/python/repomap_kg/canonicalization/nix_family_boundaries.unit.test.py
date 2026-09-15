import unittest

from repomap_kg.canonicalization.main import (
    canonicalize_observations,
)
from repomap_kg.observations.raw import RawObservation


class CanonicalizationNixFamilyBoundariesUnitTests(unittest.TestCase):
    def test_nix_import_dynamic_target_uses_placeholder(self):
        observation = RawObservation(
            kind="nix.import",
            source_id="flake.nix#nix-import:2:dynamic",
            path="flake.nix",
            start_line=2,
            end_line=2,
            confidence="heuristic",
            extractor="repo-nix",
            extractor_version="0.1.0",
            metadata={
                "import_path": "${modulePath}",
                "dynamic_reason": "nix-import-interpolation",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["infos"], 1)
        self.assertEqual(payload["diagnostics"][0]["category"], "dynamic_target")
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "dynamic:file:nix-import-interpolation",
        )

    def test_nix_import_preserves_placeholder_target_without_resolved_path(self):
        observation = RawObservation(
            kind="nix.import",
            source_id="flake.nix#nix-import:2:external",
            path="flake.nix",
            start_line=2,
            end_line=2,
            target="external:file:flake-input-module",
            confidence="heuristic",
            extractor="repo-nix",
            extractor_version="0.1.0",
            metadata={"import_path": "inputs.module"},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 0)
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "external:file:flake-input-module",
        )

    def test_nix_import_with_malformed_target_uses_unknown_placeholder(self):
        observation = RawObservation(
            kind="nix.import",
            source_id="flake.nix#nix-import:2:bad",
            path="flake.nix",
            start_line=2,
            end_line=2,
            target="file:bad%2",
            confidence="heuristic",
            extractor="repo-nix",
            extractor_version="0.1.0",
            metadata={"import_path": "./bad.nix"},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(
            payload["diagnostics"][0]["category"],
            "malformed_percent_escape",
        )
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "unknown:file:unresolved-nix-import",
        )

    def test_nix_import_with_invalid_resolved_path_uses_unknown_placeholder(self):
        observation = RawObservation(
            kind="nix.import",
            source_id="flake.nix#nix-import:2:outside",
            path="flake.nix",
            start_line=2,
            end_line=2,
            target="file:outside.nix",
            confidence="heuristic",
            extractor="repo-nix",
            extractor_version="0.1.0",
            metadata={
                "import_path": "../outside.nix",
                "resolved_path": "../outside.nix",
                "resolution": "unknown",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(payload["diagnostics"][0]["field"], "metadata.resolved_path")
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "unknown:file:repo-escaping-nix-import",
        )

    def test_nix_import_without_target_or_resolution_uses_unknown_placeholder(self):
        observation = RawObservation(
            kind="nix.import",
            source_id="flake.nix#nix-import:2:missing",
            path="flake.nix",
            start_line=2,
            end_line=2,
            confidence="heuristic",
            extractor="repo-nix",
            extractor_version="0.1.0",
            metadata={"import_path": "inputs.module"},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(payload["diagnostics"][0]["category"], "unknown_target")
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "unknown:file:unresolved-nix-import",
        )

    def test_nix_app_repo_escaping_program_path_uses_unknown_placeholder(self):
        observation = RawObservation(
            kind="nix.app",
            source_id="flake.nix#nix-app:aarch64-darwin:tool",
            path="flake.nix",
            start_line=4,
            end_line=7,
            name="tool",
            confidence="heuristic",
            extractor="repo-nix",
            extractor_version="0.1.0",
            metadata={
                "flake_ref": "repo-map",
                "system": "aarch64-darwin",
                "name": "tool",
                "attr_path": "apps.aarch64-darwin.tool",
                "output_kind": "app",
                "program_path": "../outside/tool",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(payload["diagnostics"][0]["field"], "metadata.program_path")
        self.assertEqual(
            payload["edges"][1]["target_key"],
            "unknown:file:repo-escaping-nix-app-program",
        )

    def test_nix_output_unknown_output_kind_uses_generic_name_metadata(self):
        observation = RawObservation(
            kind="nix.package",
            source_id="flake.nix#nix-package:aarch64-darwin:tool",
            path="flake.nix",
            start_line=2,
            end_line=2,
            name="tool",
            target="nix.package:repo-map:aarch64-darwin:tool",
            confidence="heuristic",
            extractor="repo-nix",
            extractor_version="0.1.0",
            metadata={
                "flake_ref": "repo-map",
                "system": "aarch64-darwin",
                "name": "tool",
                "attr_path": "packages.aarch64-darwin.tool",
                "output_kind": "custom",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["edges"][0]["metadata"]["names"], ["tool"])

    def test_nix_output_missing_identity_uses_unknown_placeholder(self):
        observation = RawObservation(
            kind="nix.package",
            source_id="flake.nix#nix-package:missing",
            path="flake.nix",
            start_line=2,
            end_line=2,
            confidence="heuristic",
            extractor="repo-nix",
            extractor_version="0.1.0",
            metadata={"output_kind": "package"},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(
            payload["diagnostics"][0]["placeholder_key"],
            "unknown:nix.package:missing-output-identity",
        )
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "unknown:nix.package:missing-output-identity",
        )


if __name__ == "__main__":
    unittest.main()
