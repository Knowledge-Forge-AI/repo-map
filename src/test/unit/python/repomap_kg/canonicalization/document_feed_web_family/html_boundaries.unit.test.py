import unittest

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.observations.raw import RawObservation


class CanonicalizationHtmlBoundaryUnitTests(unittest.TestCase):
    def test_html_identity_precedence_and_missing_fields_are_closed(self):
        valid_observations = [
            RawObservation(
                kind="html.heading",
                source_id="heading-anchor-target",
                path="index.html",
                target="html.anchor:file%3Aindex.html:welcome",
                confidence="heuristic",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={"text_summary": "Welcome"},
            ),
            RawObservation(
                kind="html.heading",
                source_id="heading-element-target",
                path="index.html",
                target="html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fh2",
                confidence="heuristic",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={"text_summary": "Details"},
            ),
            RawObservation(
                kind="html.heading",
                source_id="heading-source-key",
                path="index.html",
                confidence="heuristic",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={
                    "source_element_key": (
                        "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fh3"
                    )
                },
            ),
            RawObservation(
                kind="html.heading",
                source_id="heading-source-pointer",
                path="index.html",
                confidence="heuristic",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={"source_element_pointer": "/html/body/h4"},
            ),
            RawObservation(
                kind="html.link",
                source_id="anchor-reference",
                path="index.html",
                target="file:guide.html",
                confidence="heuristic",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={
                    "source_key": "html.anchor:file%3Aindex.html:welcome",
                    "tag": "a",
                },
            ),
        ]

        payload = canonicalize_observations(valid_observations).to_dict()
        node_keys = {node["canonical_key"] for node in payload["nodes"]}
        edge_keys = {
            (edge["source_key"], edge["kind"], edge["target_key"])
            for edge in payload["edges"]
        }

        self.assertTrue(payload["ok"])
        self.assertIn("html.anchor:file%3Aindex.html:welcome", node_keys)
        self.assertIn(
            "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fh4",
            node_keys,
        )
        self.assertIn(
            (
                "html.anchor:file%3Aindex.html:welcome",
                "references",
                "file:guide.html",
            ),
            edge_keys,
        )

        invalid_cases: tuple[tuple[str, dict[str, str], str | None, str], ...] = (
            ("html.element", {}, None, "requires pointer"),
            ("html.heading", {}, "file:index.html", "target must be html.anchor"),
            (
                "html.heading",
                {"source_element_key": "file:index.html"},
                None,
                "source_element_key must be html.element",
            ),
            ("html.heading", {}, None, "requires source element pointer"),
            ("html.link", {}, "file:guide.html", "requires source pointer"),
        )
        for index, (kind, metadata, target, expected_message) in enumerate(
            invalid_cases
        ):
            with self.subTest(kind=kind, expected_message=expected_message):
                observation = RawObservation(
                    kind=kind,
                    source_id=f"html-invalid-{index}",
                    path="index.html",
                    target=target,
                    confidence="heuristic",
                    extractor="repo-html",
                    extractor_version="0.1.0",
                    metadata=metadata,
                )

                invalid_payload = canonicalize_observations([observation]).to_dict()

                self.assertEqual(invalid_payload["summary"]["errors"], 1)
                self.assertIn(
                    expected_message,
                    invalid_payload["diagnostics"][0]["message"],
                )

    def test_css_family_diagnostics_and_metadata_contracts(self):
        valid_observations = [
            RawObservation(
                kind="css.document",
                source_id="styles/app.css#doc",
                path="styles/app.css",
                target="css.document:file%3Astyles%2Fapp.css",
                confidence="extracted",
                extractor="repo-css",
                extractor_version="0.1.0",
                metadata={"format": "css", "reference_count": 2, "parse_error_count": 0},
            ),
            RawObservation(
                kind="css.rule",
                source_id="styles/app.css#rule:1",
                path="styles/app.css",
                target="css.rule:file%3Astyles%2Fapp.css:%2Frule%3A1",
                confidence="extracted",
                extractor="repo-css",
                extractor_version="0.1.0",
                metadata={"format": "css", "rule_pointer": "/rule:1", "selector_text": ".btn"},
            ),
            RawObservation(
                kind="css.selector",
                source_id="styles/app.css#sel:1",
                path="styles/app.css",
                target="css.selector:file%3Astyles%2Fapp.css:%2Frule%3A1%2Fselector%3A1",
                confidence="extracted",
                extractor="repo-css",
                extractor_version="0.1.0",
                metadata={
                    "format": "css",
                    "rule_pointer": "/rule:1",
                    "selector_pointer": "/rule:1/selector:1",
                    "selector_text": ".btn",
                    "matched_components": {"tag": "div", "class": "btn"},
                    "limitations": ["no-pseudo-support", "no-media-support"],
                    "not_runtime_style": True,
                },
            ),
            RawObservation(
                kind="css.selector_match",
                source_id="styles/app.css#match:1",
                path="styles/app.css",
                target="html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fdiv",
                confidence="extracted",
                extractor="repo-css-matcher",
                extractor_version="0.1.0",
                metadata={
                    "format": "css",
                    "selector_key": "css.selector:file%3Astyles%2Fapp.css:%2Frule%3A1%2Fselector%3A1",
                },
            ),
            RawObservation(
                kind="css.reference",
                source_id="styles/app.css#ref:pointer",
                path="styles/app.css",
                target="file:icons/logo.svg",
                confidence="extracted",
                extractor="repo-css",
                extractor_version="0.1.0",
                metadata={"rule_pointer": "/rule:1"},
            ),
        ]
        valid_observations.append(
            RawObservation(
                kind="css.selector",
                source_id="css-sel-rule-key",
                path="styles/app.css",
                target="css.selector:file%3Astyles%2Fapp.css:%2Frule%3A1%2Fselector%3A2",
                confidence="extracted",
                extractor="repo-css",
                extractor_version="0.1.0",
                metadata={
                    "source_rule_key": "css.rule:file%3Astyles%2Fapp.css:%2Frule%3A1",
                    "selector_text": "h1",
                    "rule_pointer": "/rule:1",
                    "selector_pointer": "/rule:1/selector:2",
                },
            )
        )

        result = canonicalize_observations(valid_observations)
        payload = result.to_dict()
        self.assertTrue(payload["ok"])
        edge_triples = {(edge["source_key"], edge["kind"], edge["target_key"]) for edge in payload["edges"]}
        self.assertIn(
            (
                "css.selector:file%3Astyles%2Fapp.css:%2Frule%3A1%2Fselector%3A1",
                "styles",
                "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fdiv",
            ),
            edge_triples,
        )

        invalid_cases: tuple[tuple[str, dict[str, str], str | None, str], ...] = (
            ("css.custom_property", {}, None, "requires property name"),
            ("css.selector", {"source_rule_key": "file:styles/app.css"}, "css.selector:file%3Astyles%2Fapp.css:%2Frule%3A1%2Fsel%3A1", "source_rule_key must be css.rule"),
            ("css.selector", {}, "css.selector:file%3Astyles%2Fapp.css:%2Frule%3A1%2Fsel%3A2", "requires rule pointer metadata"),
            ("css.reference", {"source_key": "file:styles/app.css"}, "file:target.png", "source_key must be css.rule"),
            ("css.reference", {}, "file:target.png", "requires rule pointer metadata"),
        )
        for index, (kind, metadata, target, expected_message) in enumerate(invalid_cases):
            with self.subTest(kind=kind, expected_message=expected_message):
                obs = RawObservation(
                    kind=kind,
                    source_id=f"css-invalid-{index}",
                    path="styles/app.css",
                    target=target,
                    confidence="extracted",
                    extractor="repo-css",
                    extractor_version="0.1.0",
                    metadata=metadata,
                )
                invalid_res = canonicalize_observations([obs]).to_dict()
                self.assertEqual(invalid_res["summary"]["errors"], 1)
                self.assertIn(expected_message, invalid_res["diagnostics"][0]["message"])

        from repomap_kg.canonicalization.document_css_family import _css_definition_parts
        from repomap_kg.graph.keys import GraphKeyError
        with self.assertRaises(GraphKeyError):
            _css_definition_parts(
                RawObservation(
                    kind="css.unsupported",
                    source_id="css-unsupported",
                    path="styles/app.css",
                    confidence="extracted",
                    extractor="repo-css",
                    extractor_version="0.1.0",
                    metadata={},
                ),
                0,
                [],
            )


if __name__ == "__main__":
    unittest.main()
