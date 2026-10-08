"""Integration tests for Slice 8 Group S8-C: HTML/CSS Documents to Canonical Graph and Typed Rows."""

from __future__ import annotations

import unittest

from repomap_kg.extractors.documents.css import extract_css_file_observations
from repomap_kg.extractors.documents.css_html_matching import (
    extract_css_selector_match_observations,
)
from repomap_kg.extractors.documents.html import extract_html_file_observations
from repomap_kg.storage.canonical_rows import prepare_canonical_load


class Slice8DocumentHtmlCssIntegrationTests(unittest.TestCase):
    """Integration scenarios for document extraction, selector matching, canonical graphs, and typed rows."""

    def test_s8_c01_html_css_matched_selector_relationship_and_typed_rows(self) -> None:
        """Matched HTML/CSS selectors form styles edges and materialize into typed database storage rows."""
        html_content = """<!doctype html>
<html>
  <head><link rel="stylesheet" href="styles/main.css"></head>
  <body>
    <header class="hero"><h1 id="page-title">Welcome</h1></header>
    <main><div class="card"><span class="badge">Active</span></div></main>
  </body>
</html>"""
        css_content = """
.hero, .card .badge, #page-title {
  color: #0f172a;
  padding: 1rem;
}
"""
        html_obs = extract_html_file_observations("app/index.html", html_content)
        css_obs = extract_css_file_observations("app/styles/main.css", css_content)
        matches = extract_css_selector_match_observations((*html_obs, *css_obs))

        self.assertTrue(matches)
        load = prepare_canonical_load((*html_obs, *css_obs, *matches))
        self.assertTrue(load.result.ok)

        # Verify typed rows materialized
        node_keys = {row.canonical_key for row in load.canonical_rows.nodes}
        self.assertIn("html.document:file%3Aapp%2Findex.html", node_keys)
        self.assertIn("css.document:file%3Aapp%2Fstyles%2Fmain.css", node_keys)

        edge_triples = {(row.source_key, row.edge_kind, row.target_key) for row in load.canonical_rows.edges}
        style_edges = [t for t in edge_triples if t[1] == "styles"]
        self.assertTrue(style_edges)
        self.assertGreater(len(load.raw_rows), 0)

    def test_s8_c02_html_css_unsupported_selector_combinators_and_typed_rows(self) -> None:
        """Unsupported combinators (+, ~, >), attribute selectors, and pseudo-classes are safely skipped."""
        html_content = """<!doctype html>
<html>
  <head><link rel="stylesheet" href="style.css"></head>
  <body>
    <div class="row">First</div>
    <div class="row sibling">Second</div>
    <input type="text" class="field" data-active="true">
  </body>
</html>"""
        css_content = """
.row + .sibling { margin-top: 10px; }
.row ~ .sibling { opacity: 0.8; }
.parent > .field { display: block; }
input[type="text"] { border: 1px solid #ccc; }
.field:focus { outline: none; }
.row { color: #333; }
"""
        html_obs = extract_html_file_observations("index.html", html_content)
        css_obs = extract_css_file_observations("style.css", css_content)
        matches = extract_css_selector_match_observations((*html_obs, *css_obs))

        # Only the supported simple class selector (.row) should match
        matched_texts = {m.metadata.get("selector_text") for m in matches}
        self.assertIn(".row", matched_texts)
        self.assertNotIn(".row + .sibling", matched_texts)
        self.assertNotIn(".row ~ .sibling", matched_texts)
        self.assertNotIn(".parent > .field", matched_texts)
        self.assertNotIn('input[type="text"]', matched_texts)
        self.assertNotIn(".field:focus", matched_texts)

        load = prepare_canonical_load((*html_obs, *css_obs, *matches))
        self.assertTrue(load.result.ok)
        self.assertTrue(len(load.canonical_rows.nodes) > 0)

    def test_s8_c03_html_css_descendant_selector_depth_boundaries_and_confidence(self) -> None:
        """Two-part descendant selector yields heuristic confidence; three-part selector is refused."""
        html_content = """<!doctype html>
<html>
  <head><link rel="stylesheet" href="theme.css"></head>
  <body>
    <div class="outer">
      <div class="middle">
        <span class="target">Inner Text</span>
      </div>
    </div>
  </body>
</html>"""
        css_content = """
.outer .target { font-size: 14px; }
.outer .middle .target { font-weight: bold; }
"""
        html_obs = extract_html_file_observations("tree.html", html_content)
        css_obs = extract_css_file_observations("theme.css", css_content)
        matches = extract_css_selector_match_observations((*html_obs, *css_obs))

        matched_texts = {m.metadata.get("selector_text") for m in matches}
        # 2-part descendant selector is matched with heuristic confidence
        self.assertIn(".outer .target", matched_texts)
        two_part_match = next(m for m in matches if m.metadata.get("selector_text") == ".outer .target")
        self.assertEqual(two_part_match.confidence, "heuristic")
        self.assertEqual(two_part_match.metadata.get("match_kind"), "limited-descendant")

        # 3-part descendant selector is strictly refused by depth limit (> 2 parts)
        self.assertNotIn(".outer .middle .target", matched_texts)

        load = prepare_canonical_load((*html_obs, *css_obs, *matches))
        self.assertTrue(load.result.ok)

    def test_s8_c04_html_css_relative_references_with_same_name_files_in_distinct_paths(self) -> None:
        """Same-name files in distinct directories generate non-colliding canonical identities and rows."""
        html_alpha = '<!doctype html><html><head><link rel="stylesheet" href="style.css"></head><body><h1>Alpha</h1></body></html>'
        css_alpha = 'h1 { color: red; }'

        html_beta = '<!doctype html><html><head><link rel="stylesheet" href="style.css"></head><body><h1>Beta</h1></body></html>'
        css_beta = 'h1 { color: blue; }'

        obs_alpha_html = extract_html_file_observations("docs/alpha/index.html", html_alpha)
        obs_alpha_css = extract_css_file_observations("docs/alpha/style.css", css_alpha)
        obs_beta_html = extract_html_file_observations("docs/beta/index.html", html_beta)
        obs_beta_css = extract_css_file_observations("docs/beta/style.css", css_beta)

        all_obs = (*obs_alpha_html, *obs_alpha_css, *obs_beta_html, *obs_beta_css)
        load = prepare_canonical_load(all_obs)
        self.assertTrue(load.result.ok)

        node_keys = {row.canonical_key for row in load.canonical_rows.nodes}
        self.assertIn("html.document:file%3Adocs%2Falpha%2Findex.html", node_keys)
        self.assertIn("html.document:file%3Adocs%2Fbeta%2Findex.html", node_keys)
        self.assertIn("css.document:file%3Adocs%2Falpha%2Fstyle.css", node_keys)
        self.assertIn("css.document:file%3Adocs%2Fbeta%2Fstyle.css", node_keys)

        edge_sources = {row.source_key for row in load.canonical_rows.edges}
        self.assertIn("file:docs/alpha/index.html", edge_sources)
        self.assertIn("file:docs/beta/index.html", edge_sources)

    def test_s8_c05_html_css_repo_escaping_dynamic_external_to_typed_rows(self) -> None:
        """Escaping, dynamic, and external targets produce bounded placeholder keys without authority leak."""
        html_content = """<!doctype html>
<html>
  <head>
    <link rel="stylesheet" href="../../escape.css">
    <link rel="stylesheet" href="https://cdn.example.org/remote.css">
    <script src="${BUNDLE_PATH}/app.js"></script>
  </head>
  <body><a href="../../outside.html">Outside</a></body>
</html>"""
        css_content = """
.box {
  background-image: url("../../secret.svg");
  mask: url(var(--dynamic-mask));
}
"""
        html_obs = extract_html_file_observations("web/index.html", html_content)
        css_obs = extract_css_file_observations("web/style.css", css_content)

        load = prepare_canonical_load((*html_obs, *css_obs))
        self.assertTrue(load.result.ok)

        targets = {edge.target_key for edge in load.canonical_rows.edges}
        self.assertTrue(any("repo-escaping" in t for t in targets))
        self.assertTrue(any("external.url" in t for t in targets))
        self.assertTrue(any("dynamic" in t for t in targets))

    def test_s8_c06_html_css_source_order_and_repeated_observation_determinism(self) -> None:
        """Observation ingest order and duplicate observations produce deterministic canonical row sets."""
        html_obs = extract_html_file_observations(
            "page.html",
            '<!doctype html><html><head><link rel="stylesheet" href="main.css"></head><body><p class="txt">Hi</p></body></html>',
        )
        css_obs = extract_css_file_observations("main.css", ".txt { font-size: 12px; }")
        matches = extract_css_selector_match_observations((*html_obs, *css_obs))

        # Order 1: HTML, CSS, Matches
        load1 = prepare_canonical_load((*html_obs, *css_obs, *matches))
        # Order 2: Matches, CSS, HTML
        load2 = prepare_canonical_load((*matches, *css_obs, *html_obs))
        # Order 3: Duplicates injected
        load3 = prepare_canonical_load((*html_obs, *css_obs, *matches, *html_obs, *css_obs))

        self.assertTrue(load1.result.ok)
        self.assertTrue(load2.result.ok)
        self.assertTrue(load3.result.ok)

        nodes1 = sorted(row.canonical_key for row in load1.canonical_rows.nodes)
        nodes2 = sorted(row.canonical_key for row in load2.canonical_rows.nodes)
        nodes3 = sorted(row.canonical_key for row in load3.canonical_rows.nodes)
        self.assertEqual(nodes1, nodes2)
        self.assertEqual(nodes1, nodes3)

        edges1 = sorted((row.source_key, row.edge_kind, row.target_key) for row in load1.canonical_rows.edges)
        edges2 = sorted((row.source_key, row.edge_kind, row.target_key) for row in load2.canonical_rows.edges)
        edges3 = sorted((row.source_key, row.edge_kind, row.target_key) for row in load3.canonical_rows.edges)
        self.assertEqual(edges1, edges2)
        self.assertEqual(edges1, edges3)


if __name__ == "__main__":
    import sys
    sys.exit('Direct execution unsupported; use tools/run_tests.py for container sandbox admission.')
