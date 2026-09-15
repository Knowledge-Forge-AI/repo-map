import unittest

from repomap_kg.extractors.config.nix import extract_nix_file_observations
from repomap_test_support.nix_extractor import (
    NIX_EXTRACT1_FIXTURES,
    NIX_EXTRACT3_DEFERRED_KINDS,
    NIX_OUTPUT_KINDS,
    extract_nix_extract1_fixture,
    flake_input_observations,
    kind_counts,
    read_nix_extract1_fixture,
    sections_by_name,
    serialized_observations,
)


class NixExtractorFixtureSectionUnitTests(unittest.TestCase):
    def test_nix_extract1_nested_output_sections_are_characterized(self):
        observations = extract_nix_extract1_fixture("nested_output_sections")
        counts = kind_counts(observations)

        self.assertEqual(counts["nix.import"], 2)
        self.assertEqual(counts["nix.path_ref"], 1)
        self.assertEqual(counts["nix.app"], 0)
        self.assertEqual(counts["nix.package"], 0)
        self.assertEqual(counts["nix.devShell"], 0)
        self.assertEqual(counts["nix.check"], 0)
        self.assertFalse(NIX_EXTRACT3_DEFERRED_KINDS & set(counts))

    def test_nix_extract1_helper_framework_shapes_are_characterized(self):
        observations = extract_nix_extract1_fixture("helper_frameworks")
        counts = kind_counts(observations)

        self.assertEqual(counts["nix.import"], 2)
        self.assertEqual(counts["nix.path_ref"], 0)
        self.assertFalse([
            item for item in observations if item.kind in NIX_OUTPUT_KINDS
        ])
        self.assertFalse(NIX_EXTRACT3_DEFERRED_KINDS & set(counts))

    def test_nix_extract1_flake_inputs_are_characterized_without_url_exposure(self):
        observations = extract_nix_extract1_fixture("inputs_modules_overlays")
        counts = kind_counts(observations)
        serialized = serialized_observations(observations)

        self.assertEqual(counts["nix.import"], 4)
        self.assertEqual(counts["nix.path_ref"], 0)
        self.assertNotIn("https://example.invalid", serialized)
        self.assertNotIn("github:", serialized)
        self.assertFalse(NIX_EXTRACT3_DEFERRED_KINDS & set(counts))

    def test_nix_extract1_module_and_overlay_sections_are_characterized(self):
        observations = extract_nix_extract1_fixture("inputs_modules_overlays")
        imports = [item for item in observations if item.kind == "nix.import"]

        self.assertEqual([item.target for item in imports], [
            "file:modules/example-module.nix",
            "file:modules/darwin-module.nix",
            "file:modules/home-manager-module.nix",
            "file:overlays/example-overlay.nix",
        ])
        self.assertFalse([
            item for item in observations if item.kind in NIX_OUTPUT_KINDS
        ])

    def test_nix_extract1_unsupported_shapes_do_not_fabricate_outputs(self):
        for fixture_name in NIX_EXTRACT1_FIXTURES:
            with self.subTest(fixture_name=fixture_name):
                observations = extract_nix_extract1_fixture(fixture_name)
                counts = kind_counts(observations)

                self.assertFalse([
                    item for item in observations if item.kind in NIX_OUTPUT_KINDS
                ])
                self.assertFalse(NIX_EXTRACT3_DEFERRED_KINDS & set(counts))

    def test_nix_extract2_flake_inputs_emit_safe_observations(self):
        observations = extract_nix_extract1_fixture("inputs_modules_overlays")
        flake_inputs = flake_input_observations(observations)

        self.assertEqual([item.name for item in flake_inputs], [
            "nixpkgs",
            "flake-utils",
            "repo-lib",
            "local-lib",
        ])
        self.assertEqual([
            (
                item.metadata["input_name"],
                item.metadata["syntax"],
                item.metadata["has_url"],
                item.metadata["has_follows"],
                item.metadata["source_redacted"],
                item.metadata["source_type"],
            )
            for item in flake_inputs
        ], [
            ("nixpkgs", "inputs-attrset", True, False, True, "unknown"),
            ("flake-utils", "inputs-attrset", True, False, True, "unknown"),
            ("repo-lib", "inputs-attrset", False, True, True, "follows"),
            ("local-lib", "inputs-attrset", True, False, True, "path"),
        ])
        self.assertTrue(all(item.confidence == "heuristic" for item in flake_inputs))

    def test_nix_extract2_input_observations_redact_sources(self):
        observations = extract_nix_extract1_fixture("inputs_modules_overlays")
        payload = serialized_observations(flake_input_observations(observations))

        self.assertNotIn("https://", payload)
        self.assertNotIn("example.invalid", payload)
        self.assertNotIn("path:example-module", payload)
        for item in flake_input_observations(observations):
            self.assertEqual(set(item.metadata), {
                "input_name",
                "syntax",
                "has_url",
                "has_follows",
                "source_redacted",
                "source_type",
            })

    def test_nix_extract2_nested_output_sections_emit_section_observations(self):
        observations = extract_nix_extract1_fixture("nested_output_sections")
        sections = sections_by_name(observations)

        self.assertEqual(set(sections), {"packages", "devShells", "checks"})
        self.assertEqual([
            sections[name].metadata["shape"]
            for name in ("packages", "devShells", "checks")
        ], ["nested_attrset", "nested_attrset", "nested_attrset"])
        self.assertTrue(all(
            item.metadata["section_family"] == "output"
            for item in sections.values()
        ))

    def test_nix_extract2_helper_frameworks_emit_section_observations_without_outputs(self):
        observations = extract_nix_extract1_fixture("helper_frameworks")
        sections = sections_by_name(observations)

        self.assertEqual(set(sections), {"packages", "devShells", "apps"})
        self.assertTrue(all(
            item.metadata["shape"] == "helper_framework"
            for item in sections.values()
        ))
        self.assertFalse([
            item for item in observations if item.kind in NIX_OUTPUT_KINDS
        ])

    def test_nix_extract2_module_and_overlay_sections_emit_section_observations(self):
        observations = extract_nix_extract1_fixture("inputs_modules_overlays")
        sections = sections_by_name(observations)

        self.assertEqual(set(sections), {
            "nixosModules",
            "darwinModules",
            "homeManagerModules",
            "overlays",
        })
        self.assertEqual(
            sections["nixosModules"].metadata["section_family"],
            "module",
        )
        self.assertEqual(
            sections["darwinModules"].metadata["section_family"],
            "module",
        )
        self.assertEqual(
            sections["homeManagerModules"].metadata["section_family"],
            "module",
        )
        self.assertEqual(sections["overlays"].metadata["section_family"], "overlay")
        self.assertTrue(all(
            item.metadata["shape"] == "direct_assignment"
            for item in sections.values()
        ))

    def test_nix_extract2_unsupported_shapes_emit_sections_without_fabricated_outputs(self):
        observations = extract_nix_extract1_fixture("unsupported_shapes")
        sections = sections_by_name(observations)

        self.assertEqual(set(sections), {"packages", "checks", "templates"})
        self.assertEqual(sections["packages"].metadata["shape"], "merged_attrset")
        self.assertEqual(sections["checks"].metadata["shape"], "inherit")
        self.assertEqual(sections["templates"].metadata["shape"], "merged_attrset")
        self.assertFalse([
            item for item in observations if item.kind in NIX_OUTPUT_KINDS
        ])

    def test_nix_extract2_existing_direct_dotted_outputs_remain_stable(self):
        observations = extract_nix_file_observations(
            "flake.nix",
            (
                "{ self }: {\n"
                "  apps.aarch64-darwin.tool = { type = \"app\"; };\n"
                "  packages.aarch64-darwin.default = {};\n"
                "  devShells.aarch64-darwin.default = {};\n"
                "  checks.aarch64-darwin.unit = {};\n"
                "}\n"
            ),
            flake_ref="fixture",
        )

        sections = sections_by_name(observations)
        self.assertEqual(set(sections), {
            "apps",
            "packages",
            "devShells",
            "checks",
        })
        self.assertTrue(all(
            item.metadata["shape"] == "direct_assignment"
            for item in sections.values()
        ))
        self.assertEqual(
            [item.kind for item in observations if item.kind in NIX_OUTPUT_KINDS],
            ["nix.app", "nix.package", "nix.devShell", "nix.check"],
        )

    def test_nix_extract1_fixtures_are_public_safe(self):
        forbidden_source_markers = (
            "/Users/",
            "slair",
            "localhost",
            "internal",
            "private",
            "secret",
            "token",
            "password",
            "api_key",
            "file://",
            "ssh://",
        )
        forbidden_payload_markers = forbidden_source_markers + (
            "https://example.invalid",
            "path:example-module",
        )

        for fixture_name in NIX_EXTRACT1_FIXTURES:
            with self.subTest(fixture_name=fixture_name):
                source = read_nix_extract1_fixture(fixture_name)
                observations = extract_nix_extract1_fixture(fixture_name)
                payload = serialized_observations(observations)

                for marker in forbidden_source_markers:
                    self.assertNotIn(marker, source)
                    self.assertNotIn(marker.lower(), source.lower())
                for marker in forbidden_payload_markers:
                    self.assertNotIn(marker, payload)
                    self.assertNotIn(marker.lower(), payload.lower())
