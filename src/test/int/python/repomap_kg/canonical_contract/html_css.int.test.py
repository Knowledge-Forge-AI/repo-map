import json
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path

from repomap_kg.canonicalization import canonicalize_observations
from repomap_kg.extractors.documents.css import extract_css_file_observations
from repomap_kg.extractors.documents.css_html_matching import extract_css_selector_match_observations
from repomap_kg.extractors.documents.html import extract_html_file_observations
from repomap_kg.graph.discovery import extract_css_file_observations_from_file
from repomap_kg.observations import RawObservation


def _obs(
    kind: str,
    source_id: str,
    path: str = "index.html",
    *,
    name: str | None = None,
    target: str | None = None,
    confidence: str = "extracted",
    extractor: str = "repo-html",
    metadata: Mapping[str, str | int | bool] | None = None,
) -> RawObservation:
    return RawObservation(
        kind=kind,
        source_id=source_id,
        path=path,
        name=name,
        target=target,
        confidence=confidence,
        extractor=extractor,
        extractor_version="0.1.0",
        metadata=dict(metadata or {}),
    )


class CanonicalHtmlCssIntegrationTests(unittest.TestCase):
    def test_static_html_extraction_and_canonicalization_contract(self):
        observations = extract_html_file_observations(
            "site/index.html",
            """<!doctype html>
<html lang="en">
  <head>
    <title>Static contract</title>
    <link rel="stylesheet" href="assets/site.css">
    <script src="assets/app.js">alert("html-contract-js")</script>
    <style>.token-banner { color: red; }</style>
  </head>
  <body>
    <h1 id="welcome">Welcome</h1>
    <h2>Plain Heading</h2>
    <a href="#welcome">Jump</a>
    <a href="https://example.com/docs">Docs</a>
    <a href="mailto:dev@example.com">Email</a>
    <a href="javascript:alert('html-contract-js')">Bad</a>
    <a href="../../outside.html">Outside</a>
    <a href="/Library/file.txt">Absolute</a>
    <a href="${ASSET_DIR}/logo.png">Dynamic</a>
    <img src="images/logo.png">
    <form method="post" action="submit/login">
      <input name="password" value="html-contract-secret">
    </form>
  </body>
</html>
""",
        )
        broken = extract_html_file_observations("site/broken.html", "<html><body><section><p>unterminated")
        serialized = json.dumps([o.to_dict() for o in (*observations, *broken)], sort_keys=True)
        kinds = {item.kind for item in observations}
        references = [item for item in observations if item.kind in ("html.link", "html.asset", "html.form")]
        result = canonicalize_observations((*observations, *broken))
        payload = result.to_dict()

        self.assertNotIn("html-contract-secret", serialized)
        self.assertNotIn("html-contract-js", serialized)
        self.assertTrue({"html.document", "html.element", "html.heading", "html.link", "html.asset", "html.form"}.issubset(kinds))
        self.assertEqual(broken[-1].kind, "html.parse_error")
        self.assertEqual(broken[-1].metadata["error_kind"], "recoverable-unclosed-elements")

        ref_targets = {item.target for item in references}
        for t in (
            "html.anchor:file%3Asite%2Findex.html:welcome",
            "file:site/assets/site.css",
            "external.url:https%3A%2F%2Fexample.com%2Fdocs",
            "external.url:mailto%3Adev%40example.com",
            "dynamic:url:javascript-url",
            "unknown:file:repo-escaping-config-reference",
            "external:file:absolute-config-reference",
            "dynamic:file:html-reference-expanded-from-variable",
        ):
            self.assertIn(t, ref_targets)

        self.assertTrue(result.ok)
        node_keys = {node["canonical_key"] for node in payload["nodes"]}
        self.assertIn("html.document:file%3Asite%2Findex.html", node_keys)
        self.assertIn("html.anchor:file%3Asite%2Findex.html:welcome", node_keys)
        edges = {(edge["source_key"], edge["kind"], edge["target_key"]) for edge in payload["edges"]}
        self.assertIn(("file:site/index.html", "defines", "html.document:file%3Asite%2Findex.html"), edges)
        self.assertIn(("html.element:file%3Asite%2Findex.html:%2Fhtml%2Fbody%2Fa", "references", "html.anchor:file%3Asite%2Findex.html:welcome"), edges)

    def test_static_css_non_utf8_file_extraction_contract(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "bad.css").write_bytes(b"\xff\xfe\x00")
            observations = extract_css_file_observations_from_file(root, "bad.css")
        self.assertEqual(observations, ())

    def test_static_css_extraction_and_canonicalization_contract(self):
        observations = extract_css_file_observations(
            "tools/test/report/static/report.css",
            """
/* url("https://example.com/comment-secret.png") */
@import "./reset.css";
:root { --surface: #111a24; --api-token: "css-contract-secret"; }
.report-header, .status-badge[data-status="pass"]:hover::before, #summary, main[role="main"] > .tree-grid .row + .row {
  background-image: url("../../assets/panel.svg");
  mask-image: url(data:image/svg+xml;base64,SECRET_PAYLOAD);
}
@media (max-width: 720px) { .tree-grid { grid-template-columns: minmax(0, 1fr); } }
@supports (overflow-wrap: anywhere) { .path-cell { overflow-wrap: anywhere; } }
@font-face { font-family: "Report Mono"; src: url("/Library/Fonts/report.woff2") format("woff2"); }
.external { background-image: url("https://example.com/report.png"); }
.escaping { background-image: url("../../../../../outside.svg"); }
.dynamic { background-image: url(var(--asset-url)); }
.javascript { background-image: url("javascript:alert(1)"); }
@layer utilities { .layered { color: green; } }
@broken
""",
        )
        serialized = json.dumps([o.to_dict() for o in observations], sort_keys=True)
        kinds = {item.kind for item in observations}
        references = [item for item in observations if item.kind == "css.reference"]
        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertNotIn("css-contract-secret", serialized)
        self.assertNotIn("SECRET_PAYLOAD", serialized)
        self.assertNotIn("comment-secret", serialized)
        self.assertTrue({"css.document", "css.rule", "css.selector", "css.declaration", "css.custom_property", "css.reference", "css.parse_error"}.issubset(kinds))

        ref_targets = {item.target for item in references}
        for t in (
            "file:tools/test/report/static/reset.css",
            "file:tools/test/assets/panel.svg",
            "external.url:https%3A%2F%2Fexample.com%2Freport.png",
            "unknown:file:repo-escaping-css-reference",
            "unknown:external.url:data-url-payload-redacted",
            "dynamic:file:css-url-dynamic",
            "dynamic:url:unsupported-css-url-scheme",
        ):
            self.assertIn(t, ref_targets)

        self.assertTrue(result.ok)
        node_keys = {node["canonical_key"] for node in payload["nodes"]}
        self.assertIn("css.document:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css", node_keys)
        self.assertIn("css.selector:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css:%2Frule%3A2%2Fselector%3A2", node_keys)
        self.assertIn("css.custom_property:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css:--surface", node_keys)
        edge_keys = {(edge["source_key"], edge["kind"], edge["target_key"]) for edge in payload["edges"]}
        self.assertIn(("file:tools/test/report/static/report.css", "defines", "css.document:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css"), edge_keys)
        self.assertIn(("css.rule:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css:%2Frule%3A2", "references", "file:tools/test/assets/panel.svg"), edge_keys)

    def test_css_html_selector_matching_and_canonicalization_contract(self):
        html_observations = extract_html_file_observations(
            "index.html",
            """<!doctype html>
<html>
  <head>
    <link rel="stylesheet" href="static/report.css">
    <link rel="stylesheet" href="https://example.com/remote.css">
  </head>
  <body>
    <header class="report-header"><span class="status-badge status-passed">Passed</span></header>
    <main id="welcome">
      <a class="external" href="https://example.com/docs">Docs</a>
      <h1 id="heading">Heading</h1>
      <div id="dup" class="status-badge">dup one</div>
      <div id="dup">dup two</div>
      <script>window.generated = true;</script>
    </main>
  </body>
</html>
""",
        )
        css_observations = extract_css_file_observations(
            "static/report.css",
            """.status-badge, #welcome, #heading, a.external, .status-badge.status-passed,
.report-header .status-badge, .a > .b, .status-badge:hover, #dup { color: #f8fafc; }
""",
        )
        observations = html_observations + css_observations
        matches = extract_css_selector_match_observations(observations)
        result = canonicalize_observations(observations + matches)
        payload = result.to_dict()

        self.assertTrue(matches)
        self.assertTrue(all(item.kind == "css.selector_match" for item in matches))
        self.assertTrue(all(item.metadata["not_runtime_style"] is True for item in matches))
        self.assertNotIn(".status-badge:hover", {item.metadata["selector_text"] for item in matches})
        self.assertNotIn("#dup", {item.metadata["selector_text"] for item in matches})
        self.assertTrue(result.ok)
        styles = [edge for edge in payload["edges"] if edge["kind"] == "styles"]
        self.assertTrue(styles)
        style_pairs = {(edge["source_key"], edge["target_key"]) for edge in styles}
        self.assertIn(
            (
                "css.selector:file%3Astatic%2Freport.css:%2Frule%3A1%2Fselector%3A1",
                "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fheader%2Fspan",
            ),
            style_pairs,
        )
        self.assertIn("html.anchor:file%3Aindex.html:heading", {edge["target_key"] for edge in styles})
        self.assertTrue(all(edge["metadata"]["not_runtime_style_observed"] for edge in styles))

    def test_css_html_selector_matching_skip_contracts(self):
        self.assertEqual(extract_css_selector_match_observations(()), ())
        link_meta = {"tag": "link", "attribute": "href"}
        observations = (
            _obs("html.asset", "index.html#stylesheet:local", target="file:static/report.css", metadata=link_meta),
            _obs("html.asset", "index.html#stylesheet:remote", target="external.url:https%3A%2F%2Fexample.com%2Fremote.css", metadata=link_meta),
            _obs("html.asset", "index.html#stylesheet:bad-key", target="bad%zz", metadata=link_meta),
            _obs("html.asset", "index.html#stylesheet:not-css", target="file:static/not-css.txt", metadata=link_meta),
            _obs("css.selector", "static/report.css#selector:missing", path="static/report.css", target="css.selector:file%3Astatic%2Freport.css:%2Frule%3A1%2Fselector%3A1", extractor="repo-css", metadata={"selector_pointer": "/rule:1/selector:1", "selector_text": ".missing"}),
            _obs("css.selector", "static/report.css#selector:malformed", path="static/report.css", target="bad%zz", extractor="repo-css", metadata={"selector_pointer": "/rule:1/selector:2", "selector_text": ".missing"}),
            _obs("css.selector", "static/report.css#selector:not-selector", path="static/report.css", target="file:static/report.css", extractor="repo-css", metadata={"selector_pointer": "/rule:1/selector:3", "selector_text": ".missing"}),
            _obs("css.selector", "static/report.css#selector:missing-text", path="static/report.css", target="css.selector:file%3Astatic%2Freport.css:%2Frule%3A1%2Fselector%3A4", extractor="repo-css", metadata={"selector_pointer": "/rule:1/selector:4"}),
            _obs("html.element", "index.html#element:div", metadata={"pointer": "/html/body/div", "tag": "div", "classes": "not-a-list"}),
            _obs("html.element", "index.html#element:missing-pointer", metadata={"tag": "div"}),
            _obs("html.heading", "index.html#heading:bad-anchor", target="bad%zz", metadata={"source_element_pointer": "/html/body/h1", "id_is_unique": True}),
        )
        self.assertEqual(extract_css_selector_match_observations(observations), ())

    def test_static_html_canonicalization_error_and_placeholder_contracts(self):
        warning_result = canonicalize_observations(
            [
                _obs("html.heading", "index.html#html-heading:/html/body/h1", name="/html/body/h1", confidence="heuristic", metadata={"format": "html", "source_element_key": "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fh1", "source_element_pointer": "/html/body/h1", "heading_level": 1}),
                _obs("html.link", "index.html#html-link:/html/body/a:href", name="/html/body/a", confidence="heuristic", metadata={"format": "html", "source_key": "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fa", "attribute": "href"}),
                _obs("html.link", "index.html#html-link:/html/body/a[2]:href", name="/html/body/a[2]", target="bad target", confidence="heuristic", metadata={"format": "html", "source_key": "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fa%5B2%5D", "attribute": "href"}),
            ]
        )
        bad_source_result = canonicalize_observations(
            [
                _obs("html.link", "index.html#html-link:/html/body/a:href", name="/html/body/a", target="external.url:https%3A%2F%2Fexample.com", confidence="heuristic", metadata={"source_key": "tool:nix"}),
            ]
        )
        missing_pointer_result = canonicalize_observations(
            [
                _obs("html.element", "index.html#element:missing", confidence="heuristic", metadata={"format": "html"}),
            ]
        )

        warning_payload = warning_result.to_dict()
        self.assertTrue(warning_result.ok)
        self.assertEqual(warning_payload["summary"]["warnings"], 2)
        self.assertIn("html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fh1", {n["canonical_key"] for n in warning_payload["nodes"]})
        self.assertEqual(warning_payload["diagnostics"][0]["placeholder_key"], "unknown:html.reference:missing-target")
        self.assertEqual(warning_payload["diagnostics"][1]["placeholder_key"], "unknown:html.reference:malformed-target")
        self.assertFalse(bad_source_result.ok)
        self.assertIn("source_key", bad_source_result.to_dict()["diagnostics"][0]["message"])
        self.assertFalse(missing_pointer_result.ok)
        self.assertIn("pointer", missing_pointer_result.to_dict()["diagnostics"][0]["message"])
