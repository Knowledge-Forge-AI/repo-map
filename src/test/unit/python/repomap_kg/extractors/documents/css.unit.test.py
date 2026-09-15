import json
import unittest

from repomap_kg.extractors.documents.css import extract_css_file_observations
from repomap_kg.graph.keys import (
    css_custom_property_key,
    css_rule_key,
    css_selector_key,
    dynamic_key,
    external_key,
    external_url_key,
    file_key,
    unknown_key,
)


class CssExtractorUnitTests(unittest.TestCase):
    def test_extracts_rules_selectors_custom_properties_and_references(self):
        observations = extract_css_file_observations(
            "styles/report.css",
            """
@import url("./reset.css");

:root {
  --surface: #101820;
  --api-token: "super-secret-token";
}

.report-header, #summary, main[data-view="tree"]:hover::before {
  background: var(--surface);
  background-image: url("../assets/bg.svg");
  cursor: pointer !important;
}

@media (max-width: 700px) {
  .tree-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

@supports (display: grid) {
  .test-grid::after {
    content: "";
  }
}

@font-face {
  font-family: "Report";
  src: url("/Library/Fonts/report.woff2") format("woff2");
}

.external {
  background: url("https://example.com/img.png");
}

.repo-escape {
  background: url("../../outside.png");
}

.data {
  background: url("data:image/png;base64,SECRET_PAYLOAD");
}

.dynamic {
  background: url(var(--asset-url));
}

.broken {
  color: red
""",
        )

        by_kind = _by_kind(observations)
        self.assertEqual(len(by_kind["css.document"]), 1)
        self.assertGreaterEqual(len(by_kind["css.rule"]), 8)
        self.assertGreaterEqual(len(by_kind["css.selector"]), 8)
        self.assertGreaterEqual(len(by_kind["css.declaration"]), 10)
        self.assertEqual(len(by_kind["css.custom_property"]), 2)
        self.assertGreaterEqual(len(by_kind["css.reference"]), 6)
        self.assertEqual(len(by_kind["css.parse_error"]), 1)

        document = by_kind["css.document"][0]
        self.assertEqual(document.target, "css.document:file%3Astyles%2Freport.css")
        self.assertEqual(document.metadata["format"], "css")
        self.assertEqual(document.metadata["parser"], "stdlib-css-conservative")
        self.assertEqual(document.metadata["source_kind"], "file")

        grouped_rule = _find_rule(by_kind["css.rule"], "/rule:2")
        self.assertEqual(grouped_rule.target, css_rule_key("styles/report.css", "/rule:2"))
        self.assertEqual(grouped_rule.metadata["selector_text"], ".report-header, #summary, main[data-view=\"tree\"]:hover::before")
        self.assertEqual(grouped_rule.metadata["declaration_count"], 3)

        selectors = {
            observation.metadata["selector_text"]: observation
            for observation in by_kind["css.selector"]
        }
        class_selector = selectors[".report-header"]
        self.assertEqual(
            class_selector.target,
            css_selector_key("styles/report.css", "/rule:2/selector:1"),
        )
        self.assertEqual(class_selector.metadata["classes"], ["report-header"])
        self.assertEqual(class_selector.metadata["selector_kind"], "simple")

        id_selector = selectors["#summary"]
        self.assertEqual(id_selector.metadata["ids"], ["summary"])

        complex_selector = selectors['main[data-view="tree"]:hover::before']
        self.assertEqual(complex_selector.metadata["element_names"], ["main"])
        self.assertEqual(complex_selector.metadata["attributes"], ["data-view"])
        self.assertEqual(complex_selector.metadata["pseudo_classes"], ["hover"])
        self.assertEqual(complex_selector.metadata["pseudo_elements"], ["before"])
        self.assertEqual(complex_selector.metadata["selector_kind"], "complex")

        media_rule = _find_rule(by_kind["css.rule"], "/media:1")
        self.assertEqual(media_rule.metadata["rule_type"], "media")
        self.assertEqual(media_rule.metadata["at_rule_name"], "media")
        nested_media_rule = _find_rule(by_kind["css.rule"], "/media:1/rule:1")
        self.assertEqual(nested_media_rule.metadata["parent_rule_pointer"], "/media:1")

        supports_rule = _find_rule(by_kind["css.rule"], "/supports:1")
        self.assertEqual(supports_rule.metadata["rule_type"], "supports")
        nested_supports_rule = _find_rule(by_kind["css.rule"], "/supports:1/rule:1")
        self.assertEqual(nested_supports_rule.metadata["parent_rule_pointer"], "/supports:1")

        font_face_rule = _find_rule(by_kind["css.rule"], "/font-face:1")
        self.assertEqual(font_face_rule.metadata["rule_type"], "font-face")
        self.assertIn("font_family_summary", font_face_rule.metadata)

        custom_targets = {observation.target for observation in by_kind["css.custom_property"]}
        self.assertEqual(
            custom_targets,
            {
                css_custom_property_key("styles/report.css", "--surface"),
                css_custom_property_key("styles/report.css", "--api-token"),
            },
        )
        secret_property = next(
            observation
            for observation in by_kind["css.custom_property"]
            if observation.name == "--api-token"
        )
        self.assertTrue(secret_property.metadata["redacted"])
        serialized = "\n".join(
            json.dumps(observation.to_dict(), sort_keys=True)
            for observation in observations
        )
        self.assertNotIn("super-secret-token", serialized)
        self.assertNotIn("SECRET_PAYLOAD", serialized)

        reference_targets = {observation.target for observation in by_kind["css.reference"]}
        self.assertIn(file_key("styles/reset.css"), reference_targets)
        self.assertIn(file_key("assets/bg.svg"), reference_targets)
        self.assertIn(
            external_key("file", "absolute-css-reference"),
            reference_targets,
        )
        self.assertIn(external_url_key("https://example.com/img.png"), reference_targets)
        self.assertIn(
            unknown_key("file", "repo-escaping-css-reference"),
            reference_targets,
        )
        self.assertIn(
            unknown_key("external.url", "data-url-payload-redacted"),
            reference_targets,
        )
        self.assertIn(dynamic_key("file", "css-url-dynamic"), reference_targets)

    def test_malformed_stylesheet_emits_parse_error_without_fabricated_rules(self):
        observations = extract_css_file_observations(
            "broken.css",
            ".report-header { color: red; .nested { color: blue; }",
        )

        by_kind = _by_kind(observations)
        self.assertEqual(len(by_kind["css.document"]), 1)
        self.assertEqual(len(by_kind["css.parse_error"]), 1)
        self.assertTrue(by_kind["css.parse_error"][0].metadata["recovered"])

    def test_static_extraction_does_not_execute_or_claim_html_matches(self):
        observations = extract_css_file_observations(
            "styles/report.css",
            """
.status-badge {
  background-image: url("javascript:alert(1)");
}
.path-cell {
  background-image: url(var(--asset-url));
}
""",
        )

        by_kind = _by_kind(observations)
        reference_targets = {
            observation.target for observation in by_kind["css.reference"]
        }
        serialized = "\n".join(
            json.dumps(observation.to_dict(), sort_keys=True)
            for observation in observations
        )

        self.assertIn(dynamic_key("url", "unsupported-css-url-scheme"), reference_targets)
        self.assertIn(dynamic_key("file", "css-url-dynamic"), reference_targets)
        self.assertNotIn("html.element", serialized)
        self.assertNotIn("matches", serialized)
        self.assertEqual(
            {
                observation.metadata["selector_text"]
                for observation in by_kind["css.selector"]
            },
            {".status-badge", ".path-cell"},
        )

    def test_at_rule_and_comment_edge_cases_are_conservative(self):
        observations = extract_css_file_observations(
            "styles/report.css",
            """
/* url("https://example.com/comment-secret.png") */
@import "./plain.css";
@layer utilities {
  .layered { color: green; }
}
@media (min-width: 1px) {
  .nested { color: red; .inner { color: blue; } }
}
@broken
""",
        )

        by_kind = _by_kind(observations)
        rule_types = {
            observation.metadata["rule_type"] for observation in by_kind["css.rule"]
        }
        reference_targets = {
            observation.target for observation in by_kind["css.reference"]
        }
        parse_error_kinds = {
            observation.metadata["error_kind"]
            for observation in by_kind["css.parse_error"]
        }
        serialized = "\n".join(
            json.dumps(observation.to_dict(), sort_keys=True)
            for observation in observations
        )

        self.assertIn(file_key("styles/plain.css"), reference_targets)
        self.assertIn("unknown-at-rule", rule_types)
        self.assertIn("unsupported-nested-style-rule", parse_error_kinds)
        self.assertIn("malformed-at-rule", parse_error_kinds)
        self.assertNotIn("comment-secret", serialized)

    def test_tokenization_preserves_strings_functions_and_reference_boundaries(self):
        observations = extract_css_file_observations(
            "styles/tokens.css",
            r'''
[data-label="alpha,beta"], :is(.alpha,.beta), .escaped {
  content: "semi;colon\"still-one-value";
  transform: calc((1 + 2) * 1px);
  color: red !IMPORTANT;
  background-image: url("icons/a)b.svg");
  mask-image: url();
  cursor: url(mailto:styles@example.com);
  list-style-image: url(icon.svg#mark);
  malformed-declaration;
  : ignored-empty-property;
}
@font-face {
  font-family: api-token;
  src: url("fonts/report.woff2");
}
''',
        )

        by_kind = _by_kind(observations)
        selectors = {
            observation.metadata["selector_text"]
            for observation in by_kind["css.selector"]
        }
        declarations = {
            observation.metadata["property_name"]: observation
            for observation in by_kind["css.declaration"]
        }
        reference_targets = {
            observation.target for observation in by_kind["css.reference"]
        }

        self.assertEqual(
            selectors,
            {'[data-label="alpha,beta"]', ":is(.alpha,.beta)", ".escaped"},
        )
        self.assertEqual(
            declarations["content"].metadata["value_summary"],
            r'"semi;colon\"still-one-value"',
        )
        self.assertEqual(declarations["transform"].metadata["value_type"], "function")
        self.assertTrue(declarations["color"].metadata["important"])
        self.assertNotIn("malformed-declaration", declarations)
        self.assertIn(
            file_key("styles/icons/a)b.svg"),
            reference_targets,
        )
        self.assertIn(
            unknown_key("css.reference", "missing-target"),
            reference_targets,
        )
        self.assertIn(
            external_url_key("mailto:styles@example.com"),
            reference_targets,
        )
        self.assertIn(file_key("styles/icon.svg"), reference_targets)
        font_rule = _find_rule(by_kind["css.rule"], "/font-face:1")
        self.assertNotIn("font_family_summary", font_rule.metadata)

    def test_unterminated_comment_is_removed_without_fabricated_rules(self):
        observations = extract_css_file_observations(
            "styles/comment.css",
            '/* .hidden { background: url("private.png"); }',
        )

        by_kind = _by_kind(observations)

        self.assertEqual(len(by_kind["css.document"]), 1)
        self.assertNotIn("css.rule", by_kind)
        self.assertNotIn("css.reference", by_kind)


def _by_kind(observations):
    by_kind: dict[str, list] = {}
    for observation in observations:
        by_kind.setdefault(observation.kind, []).append(observation)
    return by_kind


def _find_rule(observations, pointer):
    return next(
        observation
        for observation in observations
        if observation.metadata.get("rule_pointer") == pointer
    )


if __name__ == "__main__":
    unittest.main()
