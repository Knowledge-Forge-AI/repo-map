"""Unit tests for GENERAL1 document and OpenAPI public parser contracts."""

from __future__ import annotations

import json
import unittest

from repomap_kg.extractors.config.generic import extract_config_file_observations
from repomap_kg.extractors.documents.css import extract_css_file_observations
from repomap_kg.extractors.documents.html import extract_html_file_observations
from repomap_kg.graph.keys import (
    config_path_key,
    css_document_key,
    external_key,
    external_url_key,
    file_key,
    html_anchor_key,
    html_document_key,
    unknown_key,
)


class General1DocumentContractsUnitTests(unittest.TestCase):
    """Unit tests for CSS, HTML, and OpenAPI public parser contracts and boundaries."""

    def test_css_escaped_selectors_and_reference_boundaries(self) -> None:
        """CSS parser extracts escaped selectors, handles relative boundaries, and redacts secrets."""
        css_content = """\
@import url("../../../escape.css");
@import url("/opt/styles/global.css");
@import "local/theme.css";

button[data-action="save\\"item\\""], [data-filter="tag\\[0\\]"] {
  --auth-token: "sensitive-css-pass-xyz";
  --brand-color: "#0f172a";
  background-image: url("data:image/svg+xml;base64,PHN2Zz5zZWNyZXQtZGF0YTwvc3ZnPg==");
  mask-image: url("var(--theme-bg)");
}

a.nav-link.active {
  color: #3b82f6;
}

span#status-indicator {
  display: inline-block;
}
"""
        observations = extract_css_file_observations("styles/theme.css", css_content)
        payload = json.dumps([o.to_dict() for o in observations], sort_keys=True)

        self.assertNotIn("sensitive-css-pass-xyz", payload)
        self.assertNotIn("PHN2Zz5zZWNyZXQtZGF0YTwvc3ZnPg==", payload)

        docs = [o for o in observations if o.kind == "css.document"]
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].target, css_document_key("styles/theme.css"))

        selectors = {
            o.metadata["selector_text"]: o for o in observations if o.kind == "css.selector"
        }
        self.assertIn(r'button[data-action="save\"item\""]', selectors)
        self.assertEqual(
            selectors[r'button[data-action="save\"item\""]'].metadata["selector_kind"],
            "complex",
        )
        self.assertEqual(
            selectors[r'button[data-action="save\"item\""]'].metadata["element_names"],
            ["button"],
        )
        self.assertEqual(
            selectors[r'button[data-action="save\"item\""]'].metadata["attributes"],
            ["data-action"],
        )

        self.assertIn("a.nav-link.active", selectors)
        self.assertEqual(selectors["a.nav-link.active"].metadata["selector_kind"], "compound")
        self.assertEqual(selectors["a.nav-link.active"].metadata["classes"], ["nav-link", "active"])
        self.assertEqual(selectors["a.nav-link.active"].metadata["element_names"], ["a"])

        self.assertIn("span#status-indicator", selectors)
        self.assertEqual(selectors["span#status-indicator"].metadata["selector_kind"], "compound")
        self.assertEqual(selectors["span#status-indicator"].metadata["ids"], ["status-indicator"])

        custom_props = {
            o.name: o for o in observations if o.kind == "css.custom_property"
        }
        self.assertTrue(custom_props["--auth-token"].metadata["redacted"])
        self.assertEqual(
            custom_props["--auth-token"].metadata["redaction_reason"],
            "secret-prone-css-custom-property",
        )
        self.assertFalse(custom_props["--brand-color"].metadata["redacted"])
        self.assertEqual(custom_props["--brand-color"].metadata["value_summary"], '"#0f172a"')

        references = [o for o in observations if o.kind == "css.reference"]
        ref_by_reason = {o.metadata["resolution_reason"]: o for o in references}

        escaping_ref = ref_by_reason["repo-escaping-file-reference"]
        self.assertEqual(escaping_ref.target, unknown_key("file", "repo-escaping-css-reference"))
        self.assertEqual(escaping_ref.confidence, "unknown")

        abs_ref = ref_by_reason["absolute-file-reference"]
        self.assertEqual(abs_ref.target, external_key("file", "absolute-css-reference"))

        data_ref = ref_by_reason["data-url-redacted"]
        self.assertEqual(data_ref.target, unknown_key("external.url", "data-url-payload-redacted"))
        self.assertTrue(data_ref.metadata["redacted"])
        self.assertEqual(data_ref.metadata["redaction_reason"], "data-url-payload-redacted")

        dynamic_ref = ref_by_reason["dynamic-css-url"]
        self.assertEqual(dynamic_ref.target, "dynamic:file:css-url-dynamic")

    def test_css_malformed_nested_syntax_and_at_rule_recovery(self) -> None:
        """CSS parser detects nested rules, unclosed at-rules and unclosed blocks with recovery."""
        unterminated_at_rule = '@charset "utf-8"'
        obs_at = extract_css_file_observations("styles/unterminated_at.css", unterminated_at_rule)
        at_errors = [o for o in obs_at if o.kind == "css.parse_error"]
        self.assertEqual(len(at_errors), 1)
        self.assertEqual(at_errors[0].metadata["error_kind"], "malformed-at-rule")
        self.assertTrue(at_errors[0].metadata["recovered"])

        unterminated_media = "@media screen {\n  .open-card { color: red;\n"
        obs_media = extract_css_file_observations("styles/unterminated_media.css", unterminated_media)
        media_errors = [o for o in obs_media if o.kind == "css.parse_error"]
        self.assertEqual(len(media_errors), 1)
        self.assertEqual(media_errors[0].metadata["error_kind"], "malformed-at-rule-block")
        self.assertTrue(media_errors[0].metadata["recovered"])

        missing_block = "p.hanging-rule"
        obs_rule = extract_css_file_observations("styles/missing_block.css", missing_block)
        rule_errors = [o for o in obs_rule if o.kind == "css.parse_error"]
        self.assertEqual(len(rule_errors), 1)
        self.assertEqual(rule_errors[0].metadata["error_kind"], "malformed-rule")
        self.assertTrue(rule_errors[0].metadata["recovered"])

        nested_and_parent = """\
@media (min-width: 600px) {
  .container {
    color: blue;
  }
}
.parent {
  .unsupported-child {
    color: red;
  }
}
"""
        obs_nested = extract_css_file_observations("styles/nested.css", nested_and_parent)
        rule_by_ptr = {o.name: o for o in obs_nested if o.kind == "css.rule"}
        self.assertIn("/media:1/rule:1", rule_by_ptr)
        self.assertEqual(rule_by_ptr["/media:1/rule:1"].metadata["parent_rule_pointer"], "/media:1")

        nested_errors = [o for o in obs_nested if o.kind == "css.parse_error"]
        self.assertEqual(len(nested_errors), 1)
        self.assertEqual(nested_errors[0].metadata["error_kind"], "unsupported-nested-style-rule")
        self.assertTrue(nested_errors[0].metadata["recovered"])
        self.assertEqual(nested_errors[0].metadata["rule_pointer"], "/rule:1")

        doc = next(o for o in obs_nested if o.kind == "css.document")
        self.assertEqual(doc.confidence, "heuristic")
        self.assertEqual(doc.metadata["parse_error_count"], 1)

    def test_html_malformed_recovery_and_relative_boundaries(self) -> None:
        """HTML parser recovers unclosed/unmatched tags, resolves references, and redacts secrets."""
        html_content = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <title>Document Contracts</title>
  <script src="app.js"></script>
  <style>body { font-size: 14px; }</style>
</head>
<body>
  <nav>
    <a href="../../outside.html">Escaping</a>
    <a href="/site/home.html">Absolute</a>
    <a href="javascript:void(0)">Dynamic JS</a>
    <a href="ftp://files.example.invalid/data.zip">Unsupported Scheme</a>
    <a href="https://example.com/docs">External URL</a>
    <a href="#overview">Internal Anchor</a>
    <a href="#unresolved">Unresolved Anchor</a>
    <a id="token-link" href="https://auth.example.invalid/login">Secret Link</a>
  </nav>
  <main>
    <h1 id="overview">Overview</h1>
    <form action="/login" method="post">
      <input type="text" name="user">
      <input type="password" name="password" value="secret-session-pw-4321">
      <button type="submit">Submit</button>
    </form>
    <div id="dup-anchor">first</div>
    <div id="dup-anchor">second</div>
    <a href="#dup-anchor">Jump duplicate</a>
    </span>
    <aside>
      <section>Unclosed trailing section
"""
        observations = extract_html_file_observations("docs/sample.html", html_content)
        payload = json.dumps([o.to_dict() for o in observations], sort_keys=True)
        self.assertNotIn("secret-session-pw-4321", payload)

        docs = [o for o in observations if o.kind == "html.document"]
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].target, html_document_key("docs/sample.html"))

        parse_errors = {o.metadata["error_kind"]: o for o in observations if o.kind == "html.parse_error"}
        self.assertIn("recoverable-unmatched-end-tag", parse_errors)
        self.assertTrue(parse_errors["recoverable-unmatched-end-tag"].metadata["recovered"])
        self.assertIn("recoverable-unclosed-elements", parse_errors)
        self.assertTrue(parse_errors["recoverable-unclosed-elements"].metadata["recovered"])

        links = [o for o in observations if o.kind == "html.link"]
        link_by_target = {o.target: o for o in links}

        escaping_target = unknown_key("file", "repo-escaping-config-reference")
        self.assertIn(escaping_target, link_by_target)
        self.assertEqual(link_by_target[escaping_target].metadata["reference_kind"], "unknown")
        self.assertEqual(link_by_target[escaping_target].metadata["resolution_reason"], "repo-escaping-file-reference")

        abs_target = external_key("file", "absolute-config-reference")
        self.assertIn(abs_target, link_by_target)
        self.assertEqual(link_by_target[abs_target].metadata["reference_kind"], "external")

        ext_target = external_url_key("https://example.com/docs")
        self.assertIn(ext_target, link_by_target)
        self.assertEqual(link_by_target[ext_target].metadata["reference_kind"], "external.url")

        anchor_target = html_anchor_key("docs/sample.html", "overview")
        self.assertIn(anchor_target, link_by_target)
        self.assertEqual(link_by_target[anchor_target].metadata["reference_kind"], "html.anchor")

        missing_anchor_target = unknown_key("html.anchor", "unresolved-fragment")
        self.assertIn(missing_anchor_target, link_by_target)
        self.assertEqual(link_by_target[missing_anchor_target].metadata["reference_kind"], "unknown")

        secret_link = next(o for o in links if o.name == "/html/body/nav/a[8]")
        self.assertTrue(secret_link.metadata["redacted"])
        self.assertEqual(secret_link.metadata["redaction_reason"], "secret-prone-html-attribute")

        forms = [o for o in observations if o.kind == "html.form"]
        self.assertEqual(len(forms), 1)
        self.assertEqual(forms[0].metadata["method"], "post")
        self.assertEqual(forms[0].metadata["field_count"], 3)

    def test_openapi_escaped_json_pointers_and_external_references(self) -> None:
        """OpenAPI parser handles escaped JSON pointers, relative/credentialed refs, and redaction."""
        spec = """\
openapi: "3.0.3"
info:
  title: "Contracts API"
  version: "1.0.0"
paths:
  /accounts/{accountId}/api~keys/{keyId}:
    get:
      summary: "Get key"
      operationId: "retrieveKey"
      parameters:
        - name: "X-API-Key"
          in: "header"
          required: true
      responses:
        "200":
          description: "Success"
        "default":
          $ref: "#/components/schemas/Account~1Key"
  /accounts:
    get:
      operationId: "listAccounts"
      responses:
        "200":
          $ref: "./models/key.yaml#/definitions/Key"
        "400":
          $ref: "../../../outside/secret.yaml#/Shared"
        "500":
          $ref: "https://agent-user:agent-pass-999@remote.example.invalid/v2/spec.yaml#/Remote"
components:
  schemas:
    "Account/Key":
      type: "object"
      properties:
        id:
          type: "string"
        secretToken:
          type: "string"
"""
        observations = extract_config_file_observations("api/openapi.yaml", spec)
        payload = json.dumps([o.to_dict() for o in observations], sort_keys=True)
        self.assertNotIn("agent-pass-999", payload)

        paths = {o.metadata.get("path_template"): o for o in observations if o.kind == "openapi.path"}
        escaped_path = "/accounts/{accountId}/api~keys/{keyId}"
        self.assertIn(escaped_path, paths)
        expected_path_key = config_path_key(
            "api/openapi.yaml",
            "/paths/~1accounts~1{accountId}~1api~0keys~1{keyId}",
        )
        self.assertEqual(paths[escaped_path].metadata["source_path_key"], expected_path_key)

        operations = {
            o.metadata.get("path_template"): o
            for o in observations
            if o.kind == "openapi.operation" and o.metadata.get("method") == "GET"
        }
        escaped_op = operations[escaped_path]
        expected_op_key = config_path_key(
            "api/openapi.yaml",
            "/paths/~1accounts~1{accountId}~1api~0keys~1{keyId}/get",
        )
        self.assertEqual(escaped_op.metadata["source_path_key"], expected_op_key)
        # The secret-prone "retrieveKey" ID is redacted; the path remains observable.
        self.assertIsNone(escaped_op.metadata["operation_id"])
        self.assertEqual(escaped_op.name, f"GET {escaped_path}")

        list_op = operations["/accounts"]
        self.assertEqual(list_op.metadata["operation_id"], "listAccounts")
        self.assertEqual(list_op.name, "listAccounts")

        refs = [o for o in observations if o.kind == "openapi.reference"]

        internal_ref = next(o for o in refs if o.metadata.get("reference_scope") == "internal")
        expected_internal_target = config_path_key("api/openapi.yaml", "/components/schemas/Account~1Key")
        self.assertEqual(internal_ref.target, expected_internal_target)
        self.assertFalse(internal_ref.metadata["redacted"])

        local_ref = next(o for o in refs if o.target == file_key("api/models/key.yaml"))
        self.assertEqual(local_ref.metadata["reference_scope"], "local_file")
        self.assertFalse(local_ref.metadata["redacted"])
        self.assertTrue(local_ref.metadata["not_fetched"])

        escaping_ref = next(o for o in refs if o.metadata.get("redaction_reason") == "local-ref-outside-root")
        self.assertEqual(escaping_ref.target, unknown_key("file", "repo-escaping-config-reference"))
        self.assertTrue(escaping_ref.metadata["redacted"])
        self.assertEqual(escaping_ref.metadata["ref_summary"], "<redacted-local-ref>")

        credential_ref = next(o for o in refs if o.metadata.get("redaction_reason") == "credentialed-url")
        self.assertEqual(credential_ref.target, external_key("url", "credentialed-openapi-reference"))
        self.assertTrue(credential_ref.metadata["redacted"])
        self.assertEqual(credential_ref.metadata["ref_summary"], "<redacted-url>")

        errors = [o for o in observations if o.kind == "openapi.parse_error"]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].metadata["error_kind"], "openapi-local-ref-outside-root")

        redactions = [o for o in observations if o.kind == "openapi.redaction"]
        reasons = {r.metadata.get("redaction_reason") for r in redactions}
        self.assertIn("credentialed-url", reasons)
        self.assertIn("secret-prone-openapi-field", reasons)
        self.assertIn("openapi-ref-summary-only", reasons)

    def test_openapi_syntax_recovery_and_format_diagnostics(self) -> None:
        """OpenAPI parser reports malformed YAML/JSON syntax and unsupported versions."""
        yaml_dup = """\
openapi: "3.0.3"
info:
  title: "Duplicate Key Spec"
  version: "1.0.0"
paths: {}
paths: {}
"""
        obs_yaml = extract_config_file_observations("specs/openapi.yaml", yaml_dup)
        yaml_errors = [o for o in obs_yaml if o.kind == "openapi.parse_error"]
        self.assertEqual(len(yaml_errors), 1)
        self.assertEqual(yaml_errors[0].metadata["error_kind"], "malformed-openapi-yaml")
        self.assertFalse(yaml_errors[0].metadata["recovered"])

        json_bad = '{"openapi": "3.0.0", invalid_json'
        obs_json = extract_config_file_observations("specs/openapi.json", json_bad)
        json_errors = [o for o in obs_json if o.kind == "openapi.parse_error"]
        self.assertEqual(len(json_errors), 1)
        self.assertEqual(json_errors[0].metadata["error_kind"], "malformed-openapi-json")
        self.assertFalse(json_errors[0].metadata["recovered"])

        unsupported = """\
openapi: "1.0.0"
info:
  title: "Old Spec"
  version: "1.0.0"
paths: {}
"""
        obs_version = extract_config_file_observations("specs/openapi.yaml", unsupported)
        version_errors = [o for o in obs_version if o.kind == "openapi.parse_error"]
        self.assertEqual(len(version_errors), 1)
        self.assertEqual(version_errors[0].metadata["error_kind"], "unsupported-openapi-version")
        self.assertFalse(version_errors[0].metadata["recovered"])


if __name__ == "__main__":
    unittest.main()
