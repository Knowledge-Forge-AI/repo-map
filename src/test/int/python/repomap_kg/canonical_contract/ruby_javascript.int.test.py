from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.graph.keys import (
    js_class_key, js_function_key, js_method_key, js_module_key,
    ruby_class_key, ruby_method_key, ruby_module_key,
    ruby_singleton_method_key, unknown_key,
)
from repomap_kg.observations.raw import (
    RawObservation,
    read_observations_jsonl,
    write_observations_jsonl,
)
from repomap_kg.extractors.languages import javascript as javascript_module
from repomap_kg.extractors.languages import ruby as ruby_module
from repomap_kg.extractors.languages.javascript import extract_javascript_file_observations
from repomap_kg.extractors.languages.ruby import extract_ruby_file_observations
from repomap_kg.extractors.languages.ruby_helpers import _Scope


class CanonicalRubyJavascriptIntegrationTests(unittest.TestCase):
    def _assert_reference_pipeline(self, observations: list[RawObservation]) -> None:
        result = canonicalize_observations(observations)
        self.assertTrue(result.ok, result.diagnostics)
        edges = {(edge.source_key, edge.kind, edge.target_key): edge for edge in result.graph.edges}
        evidence = {item.evidence_key: item for item in result.graph.evidence}
        references = [item for item in observations if item.kind in ("ruby.reference", "js.reference")]
        self.assertTrue(references)
        for observation in references:
            source = observation.metadata["source_key"]
            assert isinstance(source, str) and observation.target is not None
            edge = edges[(source, "references", observation.target)]
            linked = [evidence[link.evidence_key] for link in result.graph.edge_evidence_links
                      if link.edge_key == edge.edge_key]
            self.assertTrue(any(item.raw_source_id == observation.source_id for item in linked))
        self.assertEqual(result.graph, canonicalize_observations(observations).graph)

    def test_nested_definition_ownership_survives_language_pipeline(self) -> None:
        ruby = list(extract_ruby_file_observations("lib/release.rb", (
            "module Release\n  class Runner\n    def run\n    end\n"
            "    def self.build\n    end\n  end\nend\n"
        )))
        javascript = list(extract_javascript_file_observations("src/release.js", (
            'import helper from "./helper.js";\nexport class Runner {\n'
            '  run() { return helper(); }\n}\nexport function release() {}\n'
        ), repository_paths=frozenset({"src/release.js", "src/helper.js"})))
        result = canonicalize_observations([*ruby, *javascript])
        self.assertTrue(result.ok, result.diagnostics)
        nodes = {node.canonical_key for node in result.graph.nodes}
        expected = {
            (ruby_class_key("Release::Runner"), "defines", ruby_method_key("Release::Runner", "run")),
            (ruby_class_key("Release::Runner"), "defines", ruby_singleton_method_key("Release::Runner", "build")),
            (js_module_key("src/release.js"), "defines", js_class_key("src/release.js", "Runner")),
            (js_class_key("src/release.js", "Runner"), "defines", js_method_key(js_class_key("src/release.js", "Runner"), "run")),
            (js_module_key("src/release.js"), "references", "file:src/helper.js"),
        }
        self.assertIn(ruby_module_key("Release"), nodes)
        self.assertTrue(expected <= {(e.source_key, e.kind, e.target_key) for e in result.graph.edges})
        self.assertFalse(any(e.source_key == ruby_module_key("Release") and
                             e.target_key == ruby_method_key("Release::Runner", "run")
                             for e in result.graph.edges))
        linked_edges = {link.edge_key for link in result.graph.edge_evidence_links}
        self.assertTrue(all(e.edge_key in linked_edges for e in result.graph.edges
                            if (e.source_key, e.kind, e.target_key) in expected))

    def test_static_ruby_extractor_edge_contracts(self):
        rb_edge = (
            'require "./local"\nrequire_relative "../outside"\nrequire "#{dynamic_name}"\n'
            'load "json"\nmodule Edge\n  FLAG = true\n  COUNT = 42\n  ITEMS = []\n  CONFIG = {}\n'
            '  class Runner\n    def self.build\n    end\n    def Edge.utility\n    end\n  end\nend\n'
        )
        vagrant = (
            'Vagrant.configure("2") do |config|\n'
            '  config.vm.synced_folder "../outside", "/vagrant/outside"\n'
            '  config.vm.synced_folder "$ROOT", "/vagrant/dynamic"\n'
            '  config.vm.synced_folder "/tmp/source", "/vagrant/absolute"\n'
            '  config.vm.synced_folder "s3://example", "/vagrant/unsupported"\nend\n'
        )
        observations = list(extract_ruby_file_observations("scripts/edge.rb", rb_edge, repository_paths=frozenset({"scripts/edge.rb", "scripts/local.rb"})))
        observations.extend(extract_ruby_file_observations("Vagrantfile", vagrant))
        observations.extend(extract_ruby_file_observations("Gemfile", 'source "https://user:pass@example.invalid:8443/rubygems?token=value&ok=1"\ngem "example_static"\n'))
        observations.extend(extract_ruby_file_observations("sinatra_app.rb", 'require "sinatra"\nget "/items/#{id}" do\nend\n'))
        observations.extend(extract_ruby_file_observations("large.rb", "x" * (600 * 1024)))

        targets = {o.target for o in observations if o.kind == "ruby.reference"}
        parse_error_kinds = {o.metadata.get("error_kind") for o in observations if o.kind == "ruby.parse_error"}
        constant_types = {o.metadata.get("constant_name"): o.metadata.get("value_type") for o in observations if o.kind == "ruby.constant"}
        payload = "\n".join(o.to_json_line() for o in observations)

        for t in (
            "file:scripts/local.rb", "unknown:file:repo-escaping-ruby-reference",
            "dynamic:ruby.reference:interpolated-require", "dynamic:ruby.reference:dynamic-path",
            "external:file:absolute-ruby-reference", "unknown:ruby.reference:unsupported-scheme",
        ):
            self.assertIn(t, targets)
        self.assertIn("dynamic-route", parse_error_kinds)
        self.assertIn("file-size-limit", parse_error_kinds)
        self.assertEqual(constant_types["FLAG"], "boolean")
        self.assertEqual(constant_types["COUNT"], "integer")
        self.assertEqual(constant_types["ITEMS"], "array")
        self.assertEqual(constant_types["CONFIG"], "hash")
        self.assertNotIn("pass@example", payload)
        self.assertNotIn("token=value", payload)
        self.assertIn("token%3DREDACTED", payload)
        self._assert_reference_pipeline(observations)

    def test_static_ruby_profile_dsl_contracts(self):
        v_code = 'Vagrant.configure("2") do |config|\n  config.vm.network "private_network", type: "dhcp"\n  config.vm.provider "virtualbox"\n  config.vm.synced_folder "https://example.invalid/assets?token=value", "/vagrant/assets"\nend\n'
        r_code = f'namespace :fixtures do\n  desc "{"a" * 140}"\n  task :prepare do\n  end\nend\n'
        s_code = 'require "sinatra/base"\nclass App < Sinatra::Base\n  configure do\n  end\n  before do\n  end\nend\n'
        c_code = 'TITLE = "hash # inside literal"\nCOUNT = 7 # outside comment\nNEGATIVE = -7\nVALUE = ENV[\'PUBLIC_NAME\']\nLONG = "' + ("a" * 144) + '"\n'
        m_code = 'require_relative "missing"\nrequire "../../escape"\nmodule Foo::Bar\n  def self.ready?\n  end\n  def Missing.owner\n  end\nend\ndef top_level\nend\n3.times do\nend\n'
        collections = [
            extract_ruby_file_observations("test/service_spec.rb", 'require "minitest/autorun"\ndescribe "Service behavior" do\n  it "records facts" do\n  end\nend\n'),
            extract_ruby_file_observations("Vagrantfile", v_code),
            extract_ruby_file_observations("Rakefile", r_code),
            extract_ruby_file_observations("sinatra_app.rb", s_code),
            extract_ruby_file_observations("config/app.rb", "class ExampleApp < Hanami::App\nend\n"),
            extract_ruby_file_observations("lib/comments.rb", c_code),
            extract_ruby_file_observations("lib/more.rb", m_code, repository_paths=frozenset({"lib/more.rb"})),
        ]
        observations = [item for collection in collections for item in collection]
        targets = {o.target for o in observations if o.kind == "ruby.reference"}
        test_cases = [o for o in observations if o.kind == "ruby.test_case"]
        test_methods = [o for o in observations if o.kind == "ruby.test_method"]
        dsl_facts = [(o.metadata.get("profile"), o.metadata.get("dsl_name"), o.metadata.get("namespace_name")) for o in observations if o.kind == "ruby.dsl"]
        vagrant_configs = {o.metadata.get("vagrant_key"): o.metadata.get("value_summary") for o in observations if o.kind == "ruby.vagrant_config"}
        profiles = {o.metadata.get("profile") for o in observations}
        constants = {o.metadata.get("constant_name"): o.metadata.get("value_type") for o in observations if o.kind == "ruby.constant"}
        payload = "\n".join(o.to_json_line() for o in observations)

        self.assertIn("minitest", profiles)
        self.assertIn("hanami", profiles)
        self.assertTrue(any(o.target is not None and o.target.endswith("describe%5B1%5D") for o in test_cases))
        self.assertTrue(any(o.metadata.get("method_name") == "it[1]" for o in test_methods))
        self.assertIn(("rake", "namespace", "fixtures"), dsl_facts)
        self.assertIn(("sinatra", "configure", None), dsl_facts)
        self.assertIn(("sinatra", "before", None), dsl_facts)
        self.assertEqual(vagrant_configs["network"], "private_network")
        self.assertEqual(vagrant_configs["provider"], "virtualbox")
        self.assertIn("external.url:https%3A%2F%2Fexample.invalid%2Fassets%3Ftoken%3DREDACTED", targets)
        self.assertIn("file:lib/missing.rb", targets)
        self.assertIn("unknown:file:repo-escaping-ruby-reference", targets)
        self.assertEqual(constants["TITLE"], "string")
        self.assertEqual(constants["COUNT"], "integer")
        self.assertEqual(constants["NEGATIVE"], "integer")
        self.assertEqual(constants["VALUE"], "expression")
        self.assertNotIn("hash # inside literal", payload)
        self.assertNotIn("outside comment", payload)
        self.assertIn("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", payload)
        self._assert_reference_pipeline(observations)

    def test_static_ruby_reference_helper_contracts(self):
        for expr, expected in [
            (ruby_module._sanitize_url("https://user:pass@example.invalid:8443/path?token=value&ok=1"), "https://example.invalid:8443/path?token=REDACTED&ok=1"),
            (ruby_module._sanitize_url("http://[broken"), "about:invalid"),
            (ruby_module._safe_summary(None), None),
            (ruby_module._safe_summary("api_key"), "REDACTED"),
            (ruby_module._safe_summary("x" * 130), "x" * 117 + "..."),
            (ruby_module._literal_type("false"), "boolean"),
            (ruby_module._literal_type("[]"), "array"),
            (ruby_module._literal_type("{}"), "hash"),
            (ruby_module._literal_type("ENV.fetch('NAME')"), "expression"),
            (ruby_module._first_literal(", '~> 1.0'"), "~> 1.0"),
            (ruby_module._first_literal(", version"), None),
            (ruby_module._require_target("lib/a.rb", "require_relative", "missing", frozenset()), ("file:lib/missing.rb", "repo-local-candidate")),
            (ruby_module._require_target("a.rb", "require", "./local", None), ("file:local.rb", "repo-local")),
            (ruby_module._require_target("a.rb", "require", "../outside", None), ("unknown:file:repo-escaping-ruby-reference", "repo-escaping")),
            (ruby_module._require_target("a.rb", "require", "json", None), ("external:ruby.require:json", "external-ruby-require")),
            (ruby_module._normalize_relative_path("lib/a.rb", "plain", default_suffix=None), "lib/plain"),
            (ruby_module._path_target("~/.ssh/config", None), "dynamic:ruby.reference:dynamic-path"),
            (ruby_module._path_target("*.rb", None), "dynamic:ruby.reference:dynamic-path"),
            (ruby_module._path_target("s3://bucket/key", None), "unknown:ruby.reference:unsupported-scheme"),
            (ruby_module._path_target("/tmp/file", None), "external:file:absolute-ruby-reference"),
            (ruby_module._path_target("../outside", None), "unknown:file:repo-escaping-ruby-reference"),
            (ruby_module._path_target("local.rb", frozenset()), "file:local.rb"),
            (ruby_module._path_target("mailto:ops@example.invalid", None), "external.url:mailto%3Aops%40example.invalid"),
            (ruby_module._method_owner("self.call", []), (None, "call", True)),
            (ruby_module._method_owner("Owner.call", []), ("Owner", "call", True)),
            (ruby_module._method_owner("call", []), (None, "call", False)),
        ]:
            self.assertEqual(expr, expected)
        self.assertFalse(ruby_module._is_secret_prone(None))
        self.assertTrue(ruby_module._is_secret_prone("rack_secret"))
        empty_stack: list[_Scope] = []
        ruby_module._pop_scope(empty_stack)
        self.assertEqual(empty_stack, [])
        self.assertFalse(ruby_module._opens_block("class Example"))
        self.assertFalse(ruby_module._opens_block("puts 1"))
        self.assertTrue(ruby_module._opens_block("3.times do"))
        self.assertTrue(ruby_module._looks_like_route_profile("generic_ruby", "Sinatra", "app.rb"))
        self.assertFalse(ruby_module._looks_like_route_profile("generic_ruby", "", "lib/app.rb"))

    def test_static_javascript_extractor_edge_contracts(self):
        js_code = (
            'import React from "react";\nimport local from "./local";\nexport { local } from "./local";\n'
            'const apiToken = "fixture-js-secret-value";\nconst value = require("../../outside");\n'
            'const absolute = import("/tmp/absolute.js");\nconst dynamic = import(`./${name}.js`);\n'
            'fetch("https://example.invalid/api?token=value&ok=1");\nimportScripts("s3://bucket/script.js");\n'
            '//# sourceMappingURL=edge.js.map\n'
        )
        observations = list(extract_javascript_file_observations("src/edge.js", js_code, repository_paths=frozenset({"src/edge.js", "src/local.js", "src/edge.js.map"})))
        observations.extend(extract_javascript_file_observations("large.js", "x" * (600 * 1024)))

        targets = {o.target for o in observations if o.kind == "js.reference"}
        parse_error_kinds = {o.metadata.get("error_kind") for o in observations if o.kind == "js.parse_error"}
        variable_metadata = {o.name: o.metadata for o in observations if o.kind == "js.variable"}
        payload = "\n".join(o.to_json_line() for o in observations)

        for t in (
            "file:src/local.js", "external:js-package:react", "unknown:file:repo-escaping-js-reference",
            "external:file:absolute-js-reference", "unknown:js.reference:unsupported-scheme", "file:src/edge.js.map",
            "external.url:https%3A%2F%2Fexample.invalid%2Fapi%3Ftoken%3DREDACTED%26ok%3D1",
        ):
            self.assertIn(t, targets)
        self.assertIn("dynamic-interpolation", parse_error_kinds)
        self.assertIn("dynamic-dynamic-import", parse_error_kinds)
        self.assertIn("file-size-limit", parse_error_kinds)
        self.assertTrue(variable_metadata["apiToken"]["redacted"])
        self.assertNotIn("fixture-js-secret-value", payload)
        self.assertIn("token%3DREDACTED", payload)
        self._assert_reference_pipeline(observations)

    def test_static_javascript_profile_contracts(self):
        worker_code = 'importScripts("https://example.invalid/sw.js");\naxios.get("https://example.invalid/api");\nclass Widget extends React.Component {\n  render() { return null; }\n}\nfunction useLocalData() {}\n'
        collections = [
            extract_javascript_file_observations("src/jest/example.test.js", "import { describe, expect, test } from '@jest/globals';\ndescribe('suite', () => { test('case', () => expect(1).toBe(1)); });\n"),
            extract_javascript_file_observations("src/react/App.jsx", "import React, { useState } from 'react';\nexport function App() { useState(0); return <Route path=\"/home\" />; }\n"),
            extract_javascript_file_observations("src/angular/app.component.ts", "import { Component } from '@angular/core';\n@Component({ templateUrl: './app.html', styleUrls: ['./app.css'] })\nexport class AppComponent {}\n", repository_paths=frozenset({"src/angular/app.component.ts", "src/angular/app.html", "src/angular/app.css"})),
            extract_javascript_file_observations("src/vue/main.ts", "import { createApp, defineComponent } from 'vue';\nconst App = defineComponent({});\n"),
            extract_javascript_file_observations("public/report.js", "export function renderReport() {}\n//# sourceMappingURL=report.js.map\n", repository_paths=frozenset({"public/report.js", "public/report.js.map"})),
            extract_javascript_file_observations("public/worker.js", worker_code),
            extract_javascript_file_observations("src/vue/routes.ts", "import { defineComponent } from 'vue';\nconst routes = [{ path: '/vue-home' }];\nconst App = defineComponent({});\n"),
        ]
        observations = [item for collection in collections for item in collection]
        profiles = {o.metadata.get("profile") for o in observations if o.kind == "js.file"}
        targets = {o.target for o in observations if o.kind == "js.reference"}
        kinds = {o.kind for o in observations}

        self.assertTrue({"jest", "react", "angular", "vue", "test_report_asset"}.issubset(profiles))
        for k in ("js.test_suite", "js.test_case", "js.test_expectation", "js.component", "js.hook", "js.route"):
            self.assertIn(k, kinds)
        for t in ("file:src/angular/app.html", "file:src/angular/app.css", "file:public/report.js.map", "external.url:https%3A%2F%2Fexample.invalid%2Fsw.js", "external.url:https%3A%2F%2Fexample.invalid%2Fapi"):
            self.assertIn(t, targets)
        self.assertTrue(any(o.metadata.get("hook_name") == "useLocalData" for o in observations))
        self.assertTrue(any(o.metadata.get("route_pattern") == "/vue-home" for o in observations))
        self._assert_reference_pipeline(observations)

    def test_static_javascript_reference_helper_contracts(self):
        for expr, expected in [
            (javascript_module._sanitize_url("https://user:pass@example.invalid:8443/path?token=value&ok=1"), "https://example.invalid:8443/path?token=REDACTED&ok=1"),
            (javascript_module._sanitize_url("http://[broken"), "http://[broken"),
            (javascript_module._safe_summary(None), None),
            (javascript_module._safe_summary("apiToken"), "REDACTED"),
            (javascript_module._safe_summary("x" * 130), "x" * 117 + "..."),
            (javascript_module._literal_type("'text'"), "string"),
            (javascript_module._literal_type("false"), "boolean"),
            (javascript_module._literal_type("null"), "null"),
            (javascript_module._literal_type("42"), "integer"),
            (javascript_module._literal_type("4.2"), "decimal"),
            (javascript_module._literal_type("[]"), "array"),
            (javascript_module._literal_type("{}"), "object"),
            (javascript_module._literal_type("handler"), "expression"),
            (javascript_module._specifier_target("src/a.js", "./local", frozenset({"src/local.ts"})), ("file:src/local.ts", "repo-local")),
            (javascript_module._specifier_target("src/a.js", "../../outside", None), ("unknown:file:repo-escaping-js-reference", "repo-escaping")),
            (javascript_module._specifier_target("src/a.js", "/tmp/file", None), ("external:file:absolute-js-reference", "absolute-file")),
            (javascript_module._specifier_target("src/a.js", "mailto:ops@example.invalid", None), ("external.url:mailto%3Aops%40example.invalid", "external-url")),
            (javascript_module._specifier_target("src/a.js", "s3://bucket/key", None), ("unknown:js.reference:unsupported-scheme", "unsupported-scheme")),
            (javascript_module._specifier_target("src/a.js", "@scope/pkg/subpath", None), ("external:js-package:%40scope%2Fpkg", "external-js-package")),
            (javascript_module._specifier_target("src/a.js", "~/app.js", None), ("dynamic:js.reference:dynamic-path", "dynamic")),
            (javascript_module._specifier_target("src/a.js", "*.js", None), ("dynamic:js.reference:dynamic-specifier", "dynamic")),
            (javascript_module._specifier_target("src/a.js", "", None), ("unknown:js.reference:empty-specifier", "unknown")),
            (javascript_module._detect_format("src/tool.mts"), "typescript"),
            (javascript_module._detect_format("src/view.tsx"), "tsx"),
            (javascript_module._detect_format("src/view.jsx"), "jsx"),
            (javascript_module._detect_profile("vite.config.ts", "", "typescript"), "node_config"),
            (javascript_module._detect_profile(".repomap/source-artifacts/source/run/payload.js", "", "javascript"), "saved_page_asset"),
            (javascript_module._detect_module_system('const x = require("x");\nexport { x };\n'), "mixed"),
            (javascript_module._strip_line_comment('const url = "http://x"; // comment'), 'const url = "http://x"; '),
            (javascript_module._route_patterns('<Route path="/ok" />', "react"), ("/ok",)),
            (javascript_module._detect_module_system("const x = 1;\n"), "script"),
            (javascript_module._detect_module_system('const x = require("x");\n'), "commonjs"),
            (javascript_module._detect_module_system("export const x = 1;\n"), "esm"),
            (javascript_module._candidate_paths("src/local")[:4], ("src/local", "src/local.js", "src/local.mjs", "src/local.cjs")),
            (javascript_module._package_name("@scope/pkg/sub"), "@scope/pkg"),
            (javascript_module._package_name("plain/sub"), "plain"),
            (javascript_module._brace_delta("if (x) { return y; }"), 0),
        ]:
            self.assertEqual(expr, expected)
        self.assertFalse(javascript_module._is_secret_prone("publicName"))
        self.assertTrue(javascript_module._is_secret_prone("firebaseApiKey"))
        self.assertTrue(javascript_module._is_dynamic_literal("*.js"))
        self.assertFalse(javascript_module._is_dynamic_literal("./local.js"))
        self.assertTrue(javascript_module._looks_like_secret_literal("BEGIN PRIVATE KEY"))
        self.assertTrue(javascript_module._looks_like_non_method("if (ready) {"))
        self.assertTrue(javascript_module._looks_like_component("Widget", "react", "jsx", ""))
        self.assertFalse(javascript_module._looks_like_component("TOKEN", "react", "jsx", ""))

    def test_mixed_language_jsonl_attribution_and_optional_reference_targets(self) -> None:
        rb_code = (
            "module Gateway\n"
            "  class Dispatcher\n"
            "    def dispatch(event)\n"
            "    end\n"
            "  end\n"
            "end\n"
        )
        js_code = (
            'import { Dispatcher } from "./gateway.js";\n'
            'export function routeEvent(event) {\n'
            '  return new Dispatcher().dispatch(event);\n'
            '}\n'
        )
        ruby_obs = list(extract_ruby_file_observations("services/gateway.rb", rb_code))
        js_obs = list(extract_javascript_file_observations(
            "src/router.js", js_code, repository_paths=frozenset({"src/router.js", "src/gateway.js"}),
        ))
        valid_reference = next(item for item in js_obs if item.kind == "js.reference")
        self.assertIsNotNone(valid_reference.target)
        source_key = valid_reference.metadata["source_key"]
        self.assertEqual(source_key, js_module_key("src/router.js"))
        missing_metadata = {
            key: value for key, value in valid_reference.metadata.items()
            if key != "target_key"
        }
        missing_reference = replace(
            valid_reference,
            source_id=f"{valid_reference.source_id}:missing",
            target=None,
            metadata=missing_metadata,
        )
        malformed_reference = replace(
            valid_reference,
            source_id=f"{valid_reference.source_id}:malformed",
            target="bad target key",
            metadata={**valid_reference.metadata, "target_key": "bad target key"},
        )
        combined = [*ruby_obs, *js_obs, missing_reference, malformed_reference]

        with tempfile.TemporaryDirectory(prefix="repomap-ruby-js-jsonl-") as temporary:
            jsonl_path = Path(temporary) / "raw_observations.jsonl"
            write_observations_jsonl(combined, jsonl_path)
            round_tripped = read_observations_jsonl(jsonl_path)

        self.assertEqual(round_tripped, combined)
        result = canonicalize_observations(round_tripped)
        self.assertTrue(result.ok, result.diagnostics)
        self.assertIn("missing_required_metadata", {d.category for d in result.diagnostics})
        self.assertIn("invalid_canonical_key", {d.category for d in result.diagnostics})

        nodes = {node.canonical_key for node in result.graph.nodes}
        for expected_key in (
            ruby_class_key("Gateway::Dispatcher"),
            ruby_method_key("Gateway::Dispatcher", "dispatch"),
            js_module_key("src/router.js"),
            js_function_key("src/router.js", "routeEvent"),
        ):
            self.assertIn(expected_key, nodes)

        valid_target = valid_reference.target
        assert valid_target is not None
        expected_edges = {
            (ruby_class_key("Gateway::Dispatcher"), "defines", ruby_method_key("Gateway::Dispatcher", "dispatch")),
            (source_key, "references", valid_target),
            (source_key, "references", unknown_key("js.reference", "missing-target")),
            (source_key, "references", unknown_key("js.reference", "malformed-target")),
        }
        edges = {(edge.source_key, edge.kind, edge.target_key): edge for edge in result.graph.edges}
        self.assertTrue(expected_edges <= set(edges))
        evidence = {item.evidence_key: item for item in result.graph.evidence}
        for observation, target in (
            (valid_reference, valid_target),
            (missing_reference, unknown_key("js.reference", "missing-target")),
            (malformed_reference, unknown_key("js.reference", "malformed-target")),
        ):
            edge = edges[(observation.metadata["source_key"], "references", target)]
            linked = [evidence[link.evidence_key] for link in result.graph.edge_evidence_links
                      if link.edge_key == edge.edge_key]
            self.assertTrue(any(item.raw_source_id == observation.source_id for item in linked))
        self.assertEqual(result.graph, canonicalize_observations(round_tripped).graph)
