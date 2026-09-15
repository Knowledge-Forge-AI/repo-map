import unittest

from repomap_kg.extractors.documents.css import extract_css_file_observations
from repomap_kg.graph.keys import file_key, unknown_key


class CssExtractorBoundariesUnitTests(unittest.TestCase):
    def test_css_support_boundary_contracts(self):
        observations = extract_css_file_observations(
            "styles/boundaries.css",
            """
@import "lib.css";
@charset "utf-8";
.unclosed {
  background: url(unclosed-path;
}
:root {
  --token: "secret_token_123";
  --clean: "normal-value";
  --binary: "\x00\x01";
  --data-url: url("data:image/png;base64,ABC");
}
, [data-name="escaped\\"quote"], , div:not(span):is(em):where(strong), not.class, is#id, where[attr] {
  ;
  color: red;
  ;
  content: "nested\\"quote";
  background-image: url("./styles/../icons/app.svg");
  mask-image: url("styles/..");
  ;
}
div > p, div + p, div ~ p {
  content: "escaped \\" decl";
}
""",
        )
        root_obs = extract_css_file_observations(
            "root.css",
            """
@font-face {
  src: url("./font.woff");
}
.empty-url {
  background: url("");
  mask-image: url(".");
}
""",
        )
        by_kind = _by_kind(observations)
        self.assertEqual(len(by_kind["css.document"]), 1)
        selectors = {
            obs.metadata["selector_text"]: obs
            for obs in by_kind.get("css.selector", [])
        }
        self.assertIn(r'[data-name="escaped\"quote"]', selectors)
        self.assertIn("div > p", selectors)
        self.assertEqual(selectors["div > p"].metadata["selector_kind"], "complex")
        not_selector = selectors["div:not(span):is(em):where(strong)"]
        self.assertEqual(
            not_selector.metadata["element_names"], ["div", "span", "em", "strong"]
        )
        self.assertEqual(selectors["not.class"].metadata["element_names"], [])
        self.assertEqual(selectors["is#id"].metadata["element_names"], [])
        self.assertEqual(selectors["where[attr]"].metadata["element_names"], [])
        custom_props = {
            obs.name: obs for obs in by_kind.get("css.custom_property", [])
        }
        self.assertTrue(custom_props["--token"].metadata["redacted"])
        self.assertFalse(custom_props["--clean"].metadata["redacted"])
        self.assertNotIn("value_summary", custom_props["--binary"].metadata)
        self.assertTrue(custom_props["--data-url"].metadata["redacted"])
        ref_targets = {obs.target for obs in by_kind.get("css.reference", [])}
        self.assertIn(file_key("styles/lib.css"), ref_targets)
        self.assertIn(file_key("styles/icons/app.svg"), ref_targets)
        self.assertIn(file_key("styles"), ref_targets)

        root_refs = {obs.target for obs in _by_kind(root_obs).get("css.reference", [])}
        self.assertIn(file_key("font.woff"), root_refs)
        self.assertIn(unknown_key("css.reference", "missing-target"), root_refs)
        self.assertIn(unknown_key("file", "repo-escaping-css-reference"), root_refs)

    def test_css_extractor_syntax_errors_and_at_rule_boundaries(self):
        observations = extract_css_file_observations(
            "styles/syntax_errors.css",
            """
@charset "utf-8";
@namespace "http://www.w3.org/2000/svg";
{
  color: blue;
}
.trailing-no-block
""",
        )
        unterminated_obs = extract_css_file_observations(
            "styles/unterminated.css",
            """
@media (min-width: 100px) {
  .unterminated-media { color: red;
""",
        )
        errors = {
            obs.metadata["error_kind"]: obs
            for obs in _by_kind(observations).get("css.parse_error", [])
        }
        unterminated_errors = {
            obs.metadata["error_kind"]: obs
            for obs in _by_kind(unterminated_obs).get("css.parse_error", [])
        }
        self.assertIn("malformed-rule", errors)
        self.assertIn("malformed-at-rule-block", unterminated_errors)

    def test_css_support_edge_and_summary_contracts(self):
        # Test empty import string, escaped at-rules, trailing commas, and summary edge cases
        observations = extract_css_file_observations(
            "styles/edge_cases.css",
            """
@import "";
@import "nested\\"escaped.css";
a, b, {
  color: red;
}
, {
  color: blue;
}
.custom-summary {
  --empty-space:   ;
  --secret-pass: "password123";
  --clean-path: url("./sub/./file.png");
}
""",
        )
        by_kind = _by_kind(observations)
        self.assertIn("css.document", by_kind)
        props = {obs.name: obs for obs in by_kind.get("css.custom_property", [])}
        self.assertTrue(props["--secret-pass"].metadata["redacted"])

        from repomap_kg.extractors.documents.css_support import (
            _is_secret_name,
            _resolve_repo_path,
            _safe_summary,
        )

        self.assertIsNone(_safe_summary(None))
        self.assertEqual(_safe_summary("data:image/png;base64,123"), "data-url-redacted")
        self.assertFalse(_is_secret_name(None))
        self.assertIsNone(_resolve_repo_path("styles/app.css", ""))
        self.assertEqual(_resolve_repo_path("styles/app.css", "./sub/./icon.svg"), "styles/sub/icon.svg")


def _by_kind(observations):
    by_kind: dict[str, list] = {}
    for observation in observations:
        by_kind.setdefault(observation.kind, []).append(observation)
    return by_kind


if __name__ == "__main__":
    unittest.main()
