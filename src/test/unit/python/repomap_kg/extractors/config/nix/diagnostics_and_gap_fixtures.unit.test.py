import unittest

from repomap_kg.extractors.config.nix import extract_nix_file_observations
from repomap_test_support.nix_extractor import (
    NIX_EXTRACT1_FIXTURES,
    NIX_EXTRACT5_GAP_FIXTURES,
    NIX_OUTPUT_KINDS,
    assert_no_concrete_or_deferred_outputs,
    diagnostic_observations,
    dynamic_shape_observations,
    extract_nix_extract1_fixture,
    kind_counts,
    read_nix_extract1_fixture,
    sections_by_name,
    serialized_observations,
    unsupported_shape_observations,
)


class NixExtractorDiagnosticsGapFixtureUnitTests(unittest.TestCase):
    def test_nix_extract3_helper_frameworks_emit_dynamic_shape_diagnostics(self):
        observations = extract_nix_extract1_fixture("helper_frameworks")
        diagnostics = dynamic_shape_observations(observations)

        self.assertEqual([
            (
                item.metadata["section"],
                item.metadata["pattern"],
                item.metadata["reason"],
                item.metadata["counted_only"],
            )
            for item in diagnostics
        ], [
            (
                "packages",
                "eachDefaultSystem",
                "helper-generated-output-section",
                True,
            ),
            ("devShells", "genAttrs", "helper-generated-output-section", True),
            ("apps", "forAllSystems", "helper-generated-output-section", True),
        ])
        self.assertTrue(all(
            item.metadata["confidence_reason"] == "dynamic-output-helper-pattern"
            for item in diagnostics
        ))

    def test_nix_extract3_unsupported_shapes_emit_unsupported_shape_diagnostics(self):
        observations = extract_nix_extract1_fixture("unsupported_shapes")
        diagnostics = unsupported_shape_observations(observations)

        self.assertEqual(
            {
                (
                    item.metadata["section"],
                    item.metadata["pattern"],
                    item.metadata["reason"],
                    item.metadata["counted_only"],
                )
                for item in diagnostics
            },
            {
                (
                    "outputs",
                    "imported_outputs",
                    "imported-output-shape-without-static-identity",
                    True,
                ),
                (
                    "outputs",
                    "merged_attrset",
                    "merged-output-attrset-without-static-identity",
                    True,
                ),
                (
                    "packages",
                    "merged_attrset",
                    "merged-output-section-without-static-identity",
                    True,
                ),
                (
                    "checks",
                    "inherit_outputs",
                    "inherited-output-section-without-static-identity",
                    True,
                ),
                (
                    "templates",
                    "template_section",
                    "template-section-is-counted-only",
                    True,
                ),
            },
        )

    def test_nix_extract3_nested_sections_emit_counted_only_diagnostics(self):
        observations = extract_nix_extract1_fixture("nested_output_sections")
        diagnostics = unsupported_shape_observations(observations)

        self.assertEqual([
            (
                item.metadata["section"],
                item.metadata["pattern"],
                item.metadata["reason"],
                item.metadata["counted_only"],
            )
            for item in diagnostics
        ], [
            (
                "packages",
                "nested_attrset_without_direct_identity",
                "nested-output-section-without-direct-identity",
                True,
            ),
            (
                "devShells",
                "nested_attrset_without_direct_identity",
                "nested-output-section-without-direct-identity",
                True,
            ),
            (
                "checks",
                "nested_attrset_without_direct_identity",
                "nested-output-section-without-direct-identity",
                True,
            ),
        ])

    def test_nix_extract3_diagnostics_redact_expressions_paths_and_urls(self):
        observations = [
            observation
            for fixture_name in NIX_EXTRACT1_FIXTURES
            for observation in extract_nix_extract1_fixture(fixture_name)
        ]
        diagnostics = diagnostic_observations(observations)
        payload = serialized_observations(diagnostics)

        self.assertTrue(diagnostics)
        self.assertNotIn("https://", payload)
        self.assertNotIn("example.invalid", payload)
        self.assertNotIn("path:example-module", payload)
        self.assertNotIn("./", payload)
        self.assertNotIn("../", payload)
        self.assertNotIn("${", payload)
        self.assertNotIn("program", payload)
        for item in diagnostics:
            self.assertEqual(set(item.metadata), {
                "pattern",
                "section",
                "reason",
                "counted_only",
                "confidence_reason",
            })

    def test_nix_extract3_dynamic_shapes_do_not_fabricate_outputs(self):
        for fixture_name in ("helper_frameworks", "unsupported_shapes"):
            with self.subTest(fixture_name=fixture_name):
                observations = extract_nix_extract1_fixture(fixture_name)

                self.assertTrue(dynamic_shape_observations(observations))
                self.assertFalse([
                    item for item in observations if item.kind in NIX_OUTPUT_KINDS
                ])

    def test_nix_extract3_direct_dotted_outputs_are_not_marked_unsupported(self):
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

        self.assertEqual(
            [item.kind for item in observations if item.kind in NIX_OUTPUT_KINDS],
            ["nix.app", "nix.package", "nix.devShell", "nix.check"],
        )
        self.assertFalse(unsupported_shape_observations(observations))

    def test_nix_extract6_wrapped_multiline_outputs_emit_sections(self):
        observations = extract_nix_extract1_fixture(
            "wrapped_multiline_outputs_sections"
        )
        counts = kind_counts(observations)
        sections = sections_by_name(observations)
        diagnostics = unsupported_shape_observations(observations)

        self.assertEqual(counts["nix.flake_input"], 2)
        self.assertEqual(counts["nix.path_ref"], 0)
        self.assertEqual(set(sections), {"packages", "devShells", "checks"})
        self.assertTrue(all(
            item.metadata["shape"] == "unknown"
            for item in sections.values()
        ))
        self.assertEqual(
            {
                (item.metadata["section"], item.metadata["pattern"])
                for item in diagnostics
            },
            {
                ("packages", "unknown_dynamic"),
                ("devShells", "unknown_dynamic"),
                ("checks", "unknown_dynamic"),
            },
        )
        self.assertFalse(dynamic_shape_observations(observations))
        assert_no_concrete_or_deferred_outputs(self, observations)

    def test_nix_extract6_inline_open_brace_outputs_emit_sections(self):
        observations = extract_nix_extract1_fixture(
            "inline_open_brace_output_sections"
        )
        counts = kind_counts(observations)
        sections = sections_by_name(observations)
        diagnostics = unsupported_shape_observations(observations)

        self.assertEqual(counts["nix.flake_input"], 0)
        self.assertEqual(counts["nix.path_ref"], 0)
        self.assertEqual(set(sections), {"apps", "packages"})
        self.assertTrue(all(
            item.metadata["shape"] == "nested_attrset"
            for item in sections.values()
        ))
        self.assertEqual(
            {
                (item.metadata["section"], item.metadata["pattern"])
                for item in diagnostics
            },
            {
                ("apps", "nested_attrset_without_direct_identity"),
                ("packages", "nested_attrset_without_direct_identity"),
            },
        )
        self.assertFalse(dynamic_shape_observations(observations))
        assert_no_concrete_or_deferred_outputs(self, observations)

    def test_nix_extract6_wrapper_generated_outputs_emit_counted_only_diagnostics(self):
        observations = extract_nix_extract1_fixture(
            "wrapper_generated_output_sections"
        )
        counts = kind_counts(observations)
        sections = sections_by_name(observations)
        diagnostics = unsupported_shape_observations(observations)

        self.assertEqual(counts["nix.flake_input"], 2)
        self.assertEqual(counts["nix.path_ref"], 0)
        self.assertEqual(set(sections), {"packages", "apps"})
        self.assertTrue(all(
            item.metadata["shape"] == "nested_attrset"
            for item in sections.values()
        ))
        self.assertEqual(
            {
                (item.metadata["section"], item.metadata["pattern"])
                for item in diagnostics
            },
            {
                ("packages", "nested_attrset_without_direct_identity"),
                ("apps", "nested_attrset_without_direct_identity"),
            },
        )
        self.assertFalse(dynamic_shape_observations(observations))
        assert_no_concrete_or_deferred_outputs(self, observations)

    def test_nix_extract6_gap_fixtures_do_not_fabricate_concrete_outputs(self):
        for fixture_name in NIX_EXTRACT5_GAP_FIXTURES:
            with self.subTest(fixture_name=fixture_name):
                observations = extract_nix_extract1_fixture(fixture_name)

                assert_no_concrete_or_deferred_outputs(self, observations)

    def test_nix_extract6_output_body_scanner_payloads_are_public_safe(self):
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
            "github:",
            "path:",
            "./",
            "../",
            "${",
            "program",
        )

        for fixture_name in NIX_EXTRACT5_GAP_FIXTURES:
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



if __name__ == "__main__":
    unittest.main()
