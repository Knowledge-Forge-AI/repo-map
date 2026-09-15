import unittest

from repomap_kg.canonicalization import canonicalize_observations
from repomap_kg.observations import RawObservation


class CanonicalizationHtmlCssFamilyBoundariesUnitTests(unittest.TestCase):
    def test_css_definition_missing_identity_metadata_reports_errors(self):
        observations = [
            RawObservation(
                kind="css.rule",
                source_id="style.css#css-rule:missing",
                path="style.css",
                confidence="heuristic",
                extractor="repo-css",
                extractor_version="0.1.0",
                metadata={"format": "css"},
            ),
            RawObservation(
                kind="css.selector",
                source_id="style.css#css-selector:missing",
                path="style.css",
                confidence="heuristic",
                extractor="repo-css",
                extractor_version="0.1.0",
                metadata={"format": "css", "selector_pointer": "/rule:1/selector:1"},
            ),
            RawObservation(
                kind="css.custom_property",
                source_id="style.css#css-custom-property:missing",
                path="style.css",
                confidence="heuristic",
                extractor="repo-css",
                extractor_version="0.1.0",
                metadata={"format": "css"},
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["errors"], 3)
        self.assertEqual(
            [diagnostic["category"] for diagnostic in payload["diagnostics"]],
            [
                "invalid_canonical_key",
                "invalid_canonical_key",
                "invalid_canonical_key",
            ],
        )

    def test_css_selector_rejects_non_rule_source_key(self):
        observation = RawObservation(
            kind="css.selector",
            source_id="style.css#css-selector:/rule:1/selector:1",
            path="style.css",
            name="/rule:1/selector:1",
            target="css.selector:file%3Astyle.css:%2Frule%3A1%2Fselector%3A1",
            confidence="heuristic",
            extractor="repo-css",
            extractor_version="0.1.0",
            metadata={
                "format": "css",
                "source_rule_key": "css.document:file%3Astyle.css",
                "selector_pointer": "/rule:1/selector:1",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["errors"], 1)
        self.assertEqual(payload["diagnostics"][0]["category"], "invalid_canonical_key")
        self.assertIn("source_rule_key", payload["diagnostics"][0]["message"])

    def test_css_identity_fallbacks_and_selector_match_metadata_are_bounded(self):
        observations = [
            RawObservation(
                kind="css.selector",
                source_id="selector-rule-pointer",
                path="style.css",
                name="/rule:1/selector:1",
                confidence="heuristic",
                extractor="repo-css",
                extractor_version="0.1.0",
                metadata={
                    "rule_pointer": "/rule:1",
                    "selector_pointer": "/rule:1/selector:1",
                    "selector_text": ".notice",
                },
            ),
            RawObservation(
                kind="css.selector_match",
                source_id="selector-match-html-key",
                path="style.css",
                name="css.selector:file%3Astyle.css:%2Frule%3A1%2Fselector%3A1",
                confidence="heuristic",
                extractor="repo-css-html-matcher",
                extractor_version="0.1.0",
                metadata={
                    "html_key": (
                        "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Faside"
                    ),
                    "matched_components": {"classes": ["notice"]},
                    "limitations": ["no-cascade", "", 7],
                    "not_runtime_style": False,
                    "scope": "local-html-css",
                },
            ),
        ]

        payload = canonicalize_observations(observations).to_dict()
        styles_edge = next(
            edge for edge in payload["edges"] if edge["kind"] == "styles"
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(
            styles_edge["source_key"],
            "css.selector:file%3Astyle.css:%2Frule%3A1%2Fselector%3A1",
        )
        self.assertEqual(
            styles_edge["target_key"],
            "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Faside",
        )
        self.assertEqual(styles_edge["metadata"]["limitations"], ["no-cascade"])
        self.assertEqual(
            styles_edge["metadata"]["matched_components"],
            [{"classes": ["notice"]}],
        )
        self.assertEqual(
            styles_edge["metadata"]["not_runtime_style_observed"],
            False,
        )

    def test_css_missing_identity_fields_fail_closed(self):
        cases: tuple[tuple[str, dict[str, str], str | None, str], ...] = (
            ("css.rule", {}, None, "requires rule pointer"),
            (
                "css.selector",
                {"rule_pointer": "/rule:1"},
                None,
                "requires selector pointer",
            ),
            (
                "css.selector",
                {"selector_pointer": "/rule:1/selector:1"},
                None,
                "requires rule pointer",
            ),
            ("css.custom_property", {}, None, "requires property name"),
            (
                "css.selector_match",
                {"html_key": "html.element:file%3Aindex.html:%2Fhtml"},
                None,
                "requires selector_key",
            ),
            (
                "css.selector_match",
                {
                    "selector_key": (
                        "css.selector:file%3Astyle.css:%2Frule%3A1%2Fselector%3A1"
                    )
                },
                None,
                "requires html target",
            ),
        )

        for index, (kind, metadata, name, expected_message) in enumerate(cases):
            with self.subTest(kind=kind, expected_message=expected_message):
                observation = RawObservation(
                    kind=kind,
                    source_id=f"css-invalid-{index}",
                    path="style.css",
                    name=name,
                    confidence="heuristic",
                    extractor="repo-css",
                    extractor_version="0.1.0",
                    metadata=metadata,
                )

                payload = canonicalize_observations([observation]).to_dict()

                self.assertEqual(payload["summary"]["errors"], 1)
                self.assertIn(expected_message, payload["diagnostics"][0]["message"])

