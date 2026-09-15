import tempfile
import unittest
from pathlib import Path

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.extractors.documents.css import extract_css_file_observations
from repomap_kg.extractors.documents.css_html_matching import (
    extract_css_selector_match_observations,
)
from repomap_kg.extractors.documents.html import extract_html_file_observations
from repomap_kg.graph.discovery import discover_observations
from repomap_kg.observations.raw import RawObservation

HTML_FIXTURE = """\
<!doctype html>
<html>
  <head>
    <link rel="stylesheet" href="static/report.css">
    <link rel="stylesheet" href="https://example.com/remote.css">
  </head>
  <body>
    <header class="report-header">
      <span class="status-badge status-passed">Passed</span>
    </header>
    <main id="welcome" class="report-body">
      <a class="external" href="https://example.com/docs">Docs</a>
      <section class="tree-grid">
        <span class="path-cell">src/main.py</span>
        <span class="metric-cell">99%</span>
        <span class="status-cell">pass</span>
      </section>
      <div class="row">row</div>
      <h1 id="heading">Heading</h1>
      <div id="dup" class="status-badge">dup one</div>
      <div id="dup">dup two</div>
    </main>
  </body>
</html>
"""

CSS_FIXTURE = """\
.status-badge,
#welcome,
#heading,
a,
a.external,
.status-badge.status-passed,
.report-header .status-badge,
.a > .b,
.status-badge:hover,
#dup {
  color: #f8fafc;
}
"""


class CssHtmlMatchingContractsUnitTests(unittest.TestCase):
    def test_discovery_appends_selector_match_observations(self):
        with self.subTest("linked fixture"):
            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                (root / "static").mkdir()
                (root / "index.html").write_text(HTML_FIXTURE)
                (root / "static" / "report.css").write_text(CSS_FIXTURE)
                (root / "static" / "unlinked.css").write_text(
                    ".status-badge { color: red; }\n"
                )

                observations = discover_observations(root)

        matches = [
            observation
            for observation in observations
            if observation.kind == "css.selector_match"
        ]

        self.assertTrue(matches)
        self.assertTrue(
            all(match.metadata["css_file"] == "static/report.css" for match in matches)
        )
        self.assertFalse(
            any(match.metadata["css_file"] == "static/unlinked.css" for match in matches)
        )

    def test_canonicalizes_selector_match_to_styles_edge(self):
        observations = (
            extract_html_file_observations("index.html", HTML_FIXTURE)
            + extract_css_file_observations("static/report.css", CSS_FIXTURE)
        )
        matches = extract_css_selector_match_observations(observations)

        result = canonicalize_observations(observations + matches)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        style_edges = [edge for edge in payload["edges"] if edge["kind"] == "styles"]
        self.assertTrue(style_edges)
        self.assertIn(
            (
                "css.selector:file%3Astatic%2Freport.css:%2Frule%3A1%2Fselector%3A1",
                "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fheader%2Fspan",
            ),
            {(edge["source_key"], edge["target_key"]) for edge in style_edges},
        )
        metadata = style_edges[0]["metadata"]
        self.assertIn("match_kinds", metadata)
        self.assertTrue(metadata["not_runtime_style_observed"])
        self.assertIn(
            "css.selector_match",
            {evidence["raw_kind"] for evidence in payload["evidence"]},
        )

    def test_selector_match_canonicalization_rejects_bad_keys(self):
        observations = [
            RawObservation(
                kind="css.selector_match",
                source_id="bad-source",
                path="static/report.css",
                name="tool:nix",
                target="html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fmain",
                confidence="heuristic",
                extractor="repo-css-html-matcher",
                extractor_version="0.1.0",
                metadata={
                    "selector_key": "tool:nix",
                    "html_key": "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fmain",
                },
            ),
            RawObservation(
                kind="css.selector_match",
                source_id="bad-target",
                path="static/report.css",
                name="css.selector:file%3Astatic%2Freport.css:%2Frule%3A1%2Fselector%3A1",
                target="tool:nix",
                confidence="heuristic",
                extractor="repo-css-html-matcher",
                extractor_version="0.1.0",
                metadata={
                    "selector_key": (
                        "css.selector:file%3Astatic%2Freport.css:"
                        "%2Frule%3A1%2Fselector%3A1"
                    ),
                    "html_key": "tool:nix",
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["errors"], 2)
        self.assertIn(
            "selector_key must be css.selector",
            payload["diagnostics"][0]["message"],
        )
        self.assertIn(
            "target must be html.element or html.anchor",
            payload["diagnostics"][1]["message"],
        )


if __name__ == "__main__":
    unittest.main()
