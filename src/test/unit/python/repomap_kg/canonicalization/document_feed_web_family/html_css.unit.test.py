import unittest

from repomap_kg.canonicalization import canonicalize_observations
from repomap_kg.extractors.documents.css import extract_css_file_observations
from repomap_kg.extractors.documents.html import extract_html_file_observations
from repomap_kg.observations import RawObservation


class CanonicalizationHtmlCssFamilyUnitTests(unittest.TestCase):
    def test_html_observations_create_structure_and_reference_edges(self):
        observations = extract_html_file_observations(
            "index.html",
            """<!doctype html>
<html lang="en">
  <head><title>Static fixture</title></head>
  <body>
    <h1 id="welcome">Welcome Home</h1>
    <a href="#welcome">Jump</a>
    <img src="images/logo.png">
    <form action="submit/login"><input name="password" value="html-canonical-secret"></form>
  </body>
</html>
""",
        )

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertIn(
            "html.document:file%3Aindex.html",
            {node["canonical_key"] for node in payload["nodes"]},
        )
        self.assertIn(
            "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fh1",
            {node["canonical_key"] for node in payload["nodes"]},
        )
        self.assertIn(
            "html.anchor:file%3Aindex.html:welcome",
            {node["canonical_key"] for node in payload["nodes"]},
        )
        self.assertIn(
            (
                "file:index.html",
                "defines",
                "html.document:file%3Aindex.html",
            ),
            {
                (edge["source_key"], edge["kind"], edge["target_key"])
                for edge in payload["edges"]
            },
        )
        self.assertIn(
            (
                "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fa",
                "references",
                "html.anchor:file%3Aindex.html:welcome",
            ),
            {
                (edge["source_key"], edge["kind"], edge["target_key"])
                for edge in payload["edges"]
            },
        )
        self.assertIn(
            (
                "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fimg",
                "references",
                "file:images/logo.png",
            ),
            {
                (edge["source_key"], edge["kind"], edge["target_key"])
                for edge in payload["edges"]
            },
        )
        self.assertIn(
            (
                "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fform",
                "references",
                "file:submit/login",
            ),
            {
                (edge["source_key"], edge["kind"], edge["target_key"])
                for edge in payload["edges"]
            },
        )
        self.assertNotIn("html-canonical-secret", str(payload))

    def test_html_reference_diagnostics_use_placeholders(self):
        observations = [
            RawObservation(
                kind="html.link",
                source_id="index.html#html-link:/html/body/a:href",
                path="index.html",
                name="/html/body/a",
                confidence="heuristic",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={
                    "format": "html",
                    "source_key": "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fa",
                    "attribute": "href",
                },
            ),
            RawObservation(
                kind="html.link",
                source_id="index.html#html-link:/html/body/a[2]:href",
                path="index.html",
                name="/html/body/a[2]",
                target="bad target",
                confidence="heuristic",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={
                    "format": "html",
                    "source_key": "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fa%5B2%5D",
                    "attribute": "href",
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 2)
        self.assertEqual(payload["diagnostics"][0]["category"], "missing_required_metadata")
        self.assertEqual(
            payload["diagnostics"][0]["placeholder_key"],
            "unknown:html.reference:missing-target",
        )
        self.assertEqual(payload["diagnostics"][1]["category"], "invalid_canonical_key")
        self.assertEqual(
            payload["diagnostics"][1]["placeholder_key"],
            "unknown:html.reference:malformed-target",
        )

    def test_html_reference_rejects_non_html_source_key(self):
        observation = RawObservation(
            kind="html.link",
            source_id="index.html#html-link:/html/body/a:href",
            path="index.html",
            name="/html/body/a",
            target="external.url:https%3A%2F%2Fexample.com",
            confidence="heuristic",
            extractor="repo-html",
            extractor_version="0.1.0",
            metadata={
                "format": "html",
                "source_key": "tool:nix",
                "attribute": "href",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["errors"], 1)
        self.assertEqual(payload["diagnostics"][0]["category"], "invalid_canonical_key")
        self.assertIn("source_key", payload["diagnostics"][0]["message"])

    def test_css_observations_create_structure_and_reference_edges(self):
        observations = extract_css_file_observations(
            "styles/report.css",
            """
@import url("./reset.css");
:root { --surface: #101820; --api-token: "css-canonical-secret"; }
.report-header, #summary { background-image: url("../assets/bg.svg"); }
@media (max-width: 700px) { .tree-grid { color: red; } }
""",
        )

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        node_keys = {node["canonical_key"] for node in payload["nodes"]}
        self.assertIn("css.document:file%3Astyles%2Freport.css", node_keys)
        self.assertIn(
            "css.rule:file%3Astyles%2Freport.css:%2Frule%3A2",
            node_keys,
        )
        self.assertIn(
            "css.selector:file%3Astyles%2Freport.css:%2Frule%3A2%2Fselector%3A1",
            node_keys,
        )
        self.assertIn(
            "css.custom_property:file%3Astyles%2Freport.css:--surface",
            node_keys,
        )
        self.assertIn(
            "css.custom_property:file%3Astyles%2Freport.css:--api-token",
            node_keys,
        )
        edge_keys = {
            (edge["source_key"], edge["kind"], edge["target_key"])
            for edge in payload["edges"]
        }
        self.assertIn(
            (
                "file:styles/report.css",
                "defines",
                "css.document:file%3Astyles%2Freport.css",
            ),
            edge_keys,
        )
        self.assertIn(
            (
                "css.rule:file%3Astyles%2Freport.css:%2Frule%3A2",
                "defines",
                "css.selector:file%3Astyles%2Freport.css:%2Frule%3A2%2Fselector%3A1",
            ),
            edge_keys,
        )
        self.assertIn(
            (
                "file:styles/report.css",
                "defines",
                "css.custom_property:file%3Astyles%2Freport.css:--surface",
            ),
            edge_keys,
        )
        self.assertIn(
            (
                "css.rule:file%3Astyles%2Freport.css:%2Fimport%3A1",
                "references",
                "file:styles/reset.css",
            ),
            edge_keys,
        )
        self.assertIn(
            (
                "css.rule:file%3Astyles%2Freport.css:%2Frule%3A2",
                "references",
                "file:assets/bg.svg",
            ),
            edge_keys,
        )
        self.assertNotIn("css-canonical-secret", str(payload))

    def test_css_reference_diagnostics_use_placeholders(self):
        observations = [
            RawObservation(
                kind="css.reference",
                source_id="style.css#css-reference:/rule:1:1",
                path="style.css",
                name="/rule:1",
                confidence="heuristic",
                extractor="repo-css",
                extractor_version="0.1.0",
                metadata={
                    "format": "css",
                    "source_key": "css.rule:file%3Astyle.css:%2Frule%3A1",
                    "rule_pointer": "/rule:1",
                },
            ),
            RawObservation(
                kind="css.reference",
                source_id="style.css#css-reference:/rule:2:1",
                path="style.css",
                name="/rule:2",
                target="bad target",
                confidence="heuristic",
                extractor="repo-css",
                extractor_version="0.1.0",
                metadata={
                    "format": "css",
                    "source_key": "css.rule:file%3Astyle.css:%2Frule%3A2",
                    "rule_pointer": "/rule:2",
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 2)
        self.assertEqual(payload["diagnostics"][0]["category"], "missing_required_metadata")
        self.assertEqual(
            payload["diagnostics"][0]["placeholder_key"],
            "unknown:css.reference:missing-target",
        )
        self.assertEqual(payload["diagnostics"][1]["category"], "invalid_canonical_key")
        self.assertEqual(
            payload["diagnostics"][1]["placeholder_key"],
            "unknown:css.reference:malformed-target",
        )

    def test_css_reference_rejects_non_css_source_key(self):
        observation = RawObservation(
            kind="css.reference",
            source_id="style.css#css-reference:/rule:1:1",
            path="style.css",
            name="/rule:1",
            target="external.url:https%3A%2F%2Fexample.com%2Ffont.woff2",
            confidence="heuristic",
            extractor="repo-css",
            extractor_version="0.1.0",
            metadata={
                "format": "css",
                "source_key": "tool:nix",
                "rule_pointer": "/rule:1",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["errors"], 1)
        self.assertEqual(payload["diagnostics"][0]["category"], "invalid_canonical_key")
        self.assertIn("source_key", payload["diagnostics"][0]["message"])
