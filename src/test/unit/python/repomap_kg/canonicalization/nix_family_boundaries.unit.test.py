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

    def test_nix_patterns_and_resolver_validation(self):
        from typing import Any
        import repomap_kg.extractors.config.nix as nix
        import repomap_kg.extractors.config.nix_resolver as nr

        self.assertEqual(nix._dynamic_output_pattern("eachDefaultSystem (system:"), "eachDefaultSystem")
        self.assertEqual(nix._dynamic_output_pattern("genAttrs ["), "genAttrs")
        self.assertEqual(nix._dynamic_output_pattern("forAllSystems ="), "forAllSystems")
        self.assertEqual(nix._dynamic_output_pattern("flake-utils.lib"), "flake-utils")
        self.assertEqual(nix._dynamic_output_pattern("flake-parts.lib"), "flake-parts")
        self.assertIsNone(nix._dynamic_output_pattern("simple = 1;"))

        self.assertIsNotNone(nix._unsupported_output_section_shape("templates", "any"))
        self.assertIsNotNone(nix._unsupported_output_section_shape("legacyPackages", "any"))
        self.assertIsNotNone(nix._unsupported_output_section_shape("packages", "nested_attrset"))
        self.assertIsNotNone(nix._unsupported_output_section_shape("packages", "merged_attrset"))
        self.assertIsNotNone(nix._unsupported_output_section_shape("packages", "dynamic"))
        self.assertIsNotNone(nix._unsupported_output_section_shape("packages", "unknown"))
        self.assertIsNone(nix._unsupported_output_section_shape("packages", "direct_assignment"))

        self.assertEqual(nix._output_section_shape("line", suffix="", in_merged_attrset=True), "merged_attrset")
        self.assertEqual(nix._output_section_shape("flake-utils.lib", suffix="", in_merged_attrset=False), "helper_framework")
        self.assertEqual(nix._output_section_shape("line", suffix="${val}", in_merged_attrset=False), "dynamic")
        self.assertEqual(nix._output_section_shape("line", suffix="foo", in_merged_attrset=False), "direct_assignment")
        self.assertEqual(nix._output_section_shape("packages = {", suffix="", in_merged_attrset=False), "nested_attrset")
        self.assertEqual(nix._output_section_shape("import ./other.nix", suffix="", in_merged_attrset=False), "dynamic")
        self.assertEqual(nix._output_section_shape("unknown line", suffix="", in_merged_attrset=False), "unknown")

        with self.assertRaises(ValueError):
            nr.NixBindingView(alias="", input_name=None, files=frozenset())
        with self.assertRaises(ValueError):
            nr.NixBindingView(alias="a", input_name="", files=frozenset())
        with self.assertRaises(ValueError):
            nr.NixBindingView(alias="a", input_name=None, files=frozenset(), binding_id="")
        with self.assertRaises(ValueError):
            nr.NixBindingView(alias="a", input_name=None, files=frozenset(), snapshot_id="")
        bad_exports_type: Any = "not-mapping"
        with self.assertRaises(ValueError):
            nr.NixBindingView(alias="a", input_name=None, files=frozenset(), module_exports=bad_exports_type)
        with self.assertRaises(ValueError):
            nr.NixBindingView(alias="a", input_name=None, files=frozenset(), module_exports={"": "val"})
        bad_exports_dict: Any = {"m": 123}
        with self.assertRaises(ValueError):
            nr.NixBindingView(alias="a", input_name=None, files=frozenset(), module_exports=bad_exports_dict)
        with self.assertRaises(ValueError):
            nr.NixBindingView(alias="a", input_name=None, files=frozenset(), module_exports={"m": [""]})

        view = nr.NixBindingView(alias="main", input_name=None, files=frozenset({"flake.nix"}), binding_id="b1", snapshot_id="s1")
        self.assertEqual(view.alias, "main")
        self.assertIn("flake.nix", view.files)


if __name__ == "__main__":
    unittest.main()
