import unittest

from repomap_test_support.nix_extractor import (
    NIX_EXTRACT7_TARGETED_FIXTURES,
    assert_no_concrete_or_deferred_outputs,
    dynamic_shape_observations,
    extract_nix_extract1_fixture,
    kind_counts,
    read_nix_extract1_fixture,
    sections_by_name,
    serialized_observations,
    unsupported_shape_observations,
)


class NixExtractorDiagnosticsGapFixtureBoundariesUnitTests(unittest.TestCase):
    def test_nix_extract7_let_bound_output_attrsets_emit_counted_only_sections(self):
        observations = extract_nix_extract1_fixture("let_bound_output_attrsets")
        counts = kind_counts(observations)
        sections = sections_by_name(observations)
        dynamic_diagnostics = dynamic_shape_observations(observations)
        unsupported_diagnostics = unsupported_shape_observations(observations)

        self.assertEqual(counts["nix.flake_input"], 2)
        self.assertEqual(counts["nix.path_ref"], 0)
        self.assertEqual(set(sections), {"packages", "apps", "devShells", "checks"})
        self.assertTrue(all(
            item.metadata["shape"] == "dynamic"
            for item in sections.values()
        ))
        self.assertEqual(
            {
                (item.metadata["section"], item.metadata["pattern"])
                for item in dynamic_diagnostics
            },
            {
                ("packages", "string_interpolation"),
                ("apps", "string_interpolation"),
                ("devShells", "string_interpolation"),
                ("checks", "string_interpolation"),
            },
        )
        self.assertEqual(
            {
                (
                    item.metadata["section"],
                    item.metadata["pattern"],
                    item.metadata["reason"],
                )
                for item in unsupported_diagnostics
            },
            {
                (
                    "packages",
                    "unknown_dynamic",
                    "dynamic-output-section-without-static-identity",
                ),
                (
                    "apps",
                    "unknown_dynamic",
                    "dynamic-output-section-without-static-identity",
                ),
                (
                    "devShells",
                    "unknown_dynamic",
                    "dynamic-output-section-without-static-identity",
                ),
                (
                    "checks",
                    "unknown_dynamic",
                    "dynamic-output-section-without-static-identity",
                ),
            },
        )

    def test_nix_extract7_targeted_gap_does_not_fabricate_concrete_outputs(self):
        for fixture_name in NIX_EXTRACT7_TARGETED_FIXTURES:
            with self.subTest(fixture_name=fixture_name):
                observations = extract_nix_extract1_fixture(fixture_name)

                assert_no_concrete_or_deferred_outputs(self, observations)

    def test_nix_extract7_targeted_gap_payload_is_public_safe(self):
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
            "example-tool",
        )

        for fixture_name in NIX_EXTRACT7_TARGETED_FIXTURES:
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

    def test_nix_extract7_existing_output_body_scanner_fixtures_remain_stable(self):
        expectations = {
            "wrapped_multiline_outputs_sections": {
                "sections": {"packages", "devShells", "checks"},
                "shape": "unknown",
            },
            "inline_open_brace_output_sections": {
                "sections": {"apps", "packages"},
                "shape": "nested_attrset",
            },
            "wrapper_generated_output_sections": {
                "sections": {"packages", "apps"},
                "shape": "nested_attrset",
            },
        }
        for fixture_name, expected in expectations.items():
            with self.subTest(fixture_name=fixture_name):
                observations = extract_nix_extract1_fixture(fixture_name)
                sections = sections_by_name(observations)

                self.assertEqual(set(sections), expected["sections"])
                self.assertTrue(all(
                    item.metadata["shape"] == expected["shape"]
                    for item in sections.values()
                ))
                assert_no_concrete_or_deferred_outputs(self, observations)


if __name__ == "__main__":
    unittest.main()
