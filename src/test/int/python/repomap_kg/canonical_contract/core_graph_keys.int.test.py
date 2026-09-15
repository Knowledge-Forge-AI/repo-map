import json
import os
import unittest
from typing import cast
from collections.abc import Mapping
from pathlib import PurePosixPath

from repomap_test_support.canonical_contract import FIXTURE_ROOT
from repomap_kg.canonicalization.records import (
    CanonicalEdge, CanonicalEdgeEvidenceLink, CanonicalEvidence,
    CanonicalGraph, CanonicalNode, CanonicalNodeEvidenceLink,
    CanonicalizationResult, canonical_edge_key,
)
from repomap_kg.canonicalization.diagnostics import CanonicalizationDiagnostic
from repomap_kg.canonicalization import canonicalize_observations
import repomap_kg.graph.keys as graph_keys
from repomap_kg.graph.keys import (
    GRAPH_KEY_VERSION, GraphKeyError, config_document_key, config_path_key,
    dynamic_key, env_key, external_key, feed_author_key, feed_category_key,
    feed_channel_key, feed_document_key, feed_item_key, file_key,
    host_category_key, html_anchor_key, html_document_key, html_element_key,
    js_class_key, js_component_key, js_file_key, js_function_key, js_method_key,
    js_module_key, js_route_key, js_test_case_key, js_test_suite_key,
    js_variable_key, nix_app_key, nix_check_key, nix_dev_shell_key,
    nix_output_key, nix_package_key, parse_key, python_class_key,
    python_function_key, python_method_key, python_module_key, ruby_class_key,
    ruby_constant_key, ruby_file_key, ruby_method_key, ruby_module_key,
    ruby_route_key, ruby_singleton_method_key, ruby_test_case_key,
    ruby_test_method_key, tool_key, unknown_key, validate_key,
    xml_attribute_key, xml_document_key, xml_element_key,
)
from repomap_kg.observations import RawObservation, read_observations_jsonl


def _obs(
    kind: str, source_id: str, path: str, *,
    extractor: str = "repo-shell",
    metadata: Mapping[str, str | int | bool | list[str]] | None = None,
    confidence: str = "heuristic",
    target: str | None = None,
) -> RawObservation:
    return RawObservation(
        kind=kind, source_id=source_id, path=path, extractor=extractor,
        extractor_version="0.1.0", metadata=dict(metadata or {}),
        confidence=confidence, target=target,
    )


class CanonicalCoreGraphKeysIntegrationTests(unittest.TestCase):
    def test_golden_fixture_serialization_matches_exact_json_contract(self):
        fixture_names = (
            "files_basic", "files_conflict", "shell_executes_nix", "shell_executes_collapse",
            "shell_source_static", "shell_source_dynamic", "shell_env_read", "shell_env_write",
            "shell_env_write_collapse", "shell_host_mutation_package", "malformed_target_rebuilt",
            "malformed_target_placeholder", "shell_source_repo_escape", "shell_env_missing_variable",
            "unsupported_kind", "python_package", "go_basic", "go_duplicate_modules",
            "nix_flake_basic", "markdown_docs_basic", "config_json_basic", "config_toml_basic",
            "config_codex_mcp_dogfood", "yaml_basic", "ruby_basic", "js_basic", "mail_basic",
            "xml_plist_chrome_policy_basic", "xml_java_spring_maven_basic", "html_static_basic",
            "css_static_basic", "feed_static_basic", "docs_odf_basic",
        )
        for fixture_name in fixture_names:
            with self.subTest(fixture_name=fixture_name):
                fixture_dir = FIXTURE_ROOT / fixture_name
                observations = read_observations_jsonl(fixture_dir / "raw_observations.jsonl")
                expected = (fixture_dir / "expected_canonical_graph.json").read_text()
                result = canonicalize_observations(observations, repository_scope=f"canonical-{fixture_name}")
                self.assertEqual(result.to_json(), expected)

    def test_canonical_key_examples_round_trip_through_parser(self):
        fc = feed_channel_key(feed_document_key("feeds/rss.xml"), "link:https://example.com/feed.xml")
        keys = [
            file_key("scripts/../bin/tool"), file_key(PurePosixPath("./docs/My Tool:guide#1.md")),
            file_key("."), tool_key("my tool"), env_key("PATH"), host_category_key("package-management"),
            python_module_key("repomap_kg.cli"), python_class_key("repomap_kg.cli", "CliError"),
            python_function_key("repomap_kg.cli", "main:debug"),
            python_method_key("repomap_kg.storage", "Record", "to_dict"),
            nix_app_key("repo-map", "aarch64-darwin", "tool#debug"),
            nix_package_key("repo-map", "aarch64-darwin", "default"),
            nix_dev_shell_key("repo-map", "aarch64-darwin", "default"),
            nix_check_key("repo-map", "aarch64-darwin", "unit"),
            nix_output_key("repo-map", "packages/aarch64-darwin/default"),
            ruby_module_key("RepoMap"), ruby_class_key("RepoMap::Runner"),
            ruby_method_key("RepoMap::Runner", "call"), ruby_file_key("lib/example.rb"),
            ruby_singleton_method_key("RepoMap::Runner", "build"),
            ruby_constant_key("RepoMap::Runner", "DEFAULTURL"),
            ruby_test_case_key("test/example_test.rb", "ExampleTest"),
            ruby_test_method_key(ruby_test_case_key("test/example_test.rb", "ExampleTest"), "test_call"),
            ruby_route_key("app.rb", "/routes/get:/health"), js_file_key("src/index.js"),
            js_module_key("src/index.js"), js_function_key("src/index.js", "main"),
            js_class_key("src/index.js", "Runner"),
            js_method_key(js_class_key("src/index.js", "Runner"), "start"),
            js_variable_key("src/index.js", "COUNT"), js_component_key("src/component.jsx", "ExampleComponent"),
            js_test_suite_key("src/jest/example.test.js", "/tests/describe[1]"),
            js_test_case_key(js_test_suite_key("src/jest/example.test.js", "/tests/describe[1]"), "/tests/test[1]"),
            js_route_key("src/react/App.jsx", "/routes/path:/home"),
            dynamic_key("file", "shell source expanded"), external_key("python.module", "requests"),
            unknown_key("env", "missing variable"), "doc.page:file%3AREADME.md",
            "doc.section:file%3AREADME.md:current-status", "doc.adr:0008",
            "doc.skill:docs-only-change-hygiene", "external.url:https%3A%2F%2Fexample.com%2Fdocs",
            config_document_key("mcp/config.json"),
            config_path_key("mcp/config.json", "/mcp_servers/repomap/command"),
            xml_document_key("pom.xml"), xml_element_key("pom.xml", "/project/dependencies/dependency[2]"),
            xml_attribute_key("src/main/resources/applicationContext.xml", "/beans/bean", "class"),
            html_document_key("site/index.html"), html_element_key("site/index.html", "/html/body/main/a[2]"),
            html_anchor_key("site/index.html", "intro"), feed_document_key("feeds/rss.xml"),
            fc, feed_item_key(fc, "guid:release:1"), feed_author_key(fc, "Fixture Writer"),
            feed_category_key(fc, "Release Notes"),
        ]

        expected_map = {
            0: "file:bin/tool", 1: "file:docs/My%20Tool%3Aguide%231.md", 2: "file:.", 3: "tool:my%20tool",
            8: "python.function:repomap_kg.cli:main%3Adebug",
            14: "nix.output:repo-map:packages%2Faarch64-darwin%2Fdefault",
            16: "ruby.class:RepoMap%3A%3ARunner", 24: "js.file:file%3Asrc%2Findex.js",
            26: "js.function:file%3Asrc%2Findex.js:main", 27: "js.class:file%3Asrc%2Findex.js:Runner",
            28: "js.method:js.class%3Afile%253Asrc%252Findex.js%3ARunner:start",
            -11: "xml.document:file%3Apom.xml",
            -10: "xml.element:file%3Apom.xml:%2Fproject%2Fdependencies%2Fdependency%5B2%5D",
            -9: "xml.attribute:file%3Asrc%2Fmain%2Fresources%2FapplicationContext.xml:%2Fbeans%2Fbean:class",
            -8: "html.document:file%3Asite%2Findex.html",
            -7: "html.element:file%3Asite%2Findex.html:%2Fhtml%2Fbody%2Fmain%2Fa%5B2%5D",
            -6: "html.anchor:file%3Asite%2Findex.html:intro", -5: "feed.document:file%3Afeeds%2Frss.xml",
            -4: "feed.channel:feed.document%3Afile%253Afeeds%252Frss.xml:link%3Ahttps%3A%2F%2Fexample.com%2Ffeed.xml",
            -3: "feed.item:feed.channel%3Afeed.document%253Afile%25253Afeeds%25252Frss.xml%3Alink%253Ahttps%253A%252F%252Fexample.com%252Ffeed.xml:guid%3Arelease%3A1",
            -2: "feed.author:feed.channel%3Afeed.document%253Afile%25253Afeeds%25252Frss.xml%3Alink%253Ahttps%253A%252F%252Fexample.com%252Ffeed.xml:Fixture%20Writer",
            -1: "feed.category:feed.channel%3Afeed.document%253Afile%25253Afeeds%25252Frss.xml%3Alink%253Ahttps%253A%252F%252Fexample.com%252Ffeed.xml:Release%20Notes",
        }
        for idx, expected_val in expected_map.items():
            self.assertEqual(keys[idx], expected_val)

        for key in keys:
            with self.subTest(key=key):
                parsed, validation = parse_key(key), validate_key(key)
                self.assertEqual(parsed.graph_key_version, GRAPH_KEY_VERSION)
                self.assertEqual(parsed.key, key)
                self.assertTrue(validation.valid)
                self.assertIsNone(validation.error)

        parsed_file = parse_key(keys[1])
        self.assertEqual(parsed_file.namespace, "file")
        self.assertEqual(parsed_file.path, "docs/My Tool:guide#1.md")
        self.assertEqual(parsed_file.segments, ("docs", "My Tool:guide#1.md"))
        self.assertIsNone(parse_key(keys[9]).path)
        self.assertEqual(parse_key(keys[-5]).namespace, "feed.document")
        self.assertEqual(parse_key(keys[-4]).namespace, "feed.channel")
        self.assertEqual(parse_key(keys[-3]).namespace, "feed.item")

    def test_canonical_key_parser_rejects_malformed_examples(self):
        cases = (
            ("tool:nix%2", "percent"), ("tool:nix%2fbuild", "uppercase"),
            ("tool:nix#build", "reserved"), ("python.module:repomap_kg.cli:extra", "segments"),
            ("file:../outside", "escape"), ("file:docs//guide.md", "empty"),
            ("not-a-key", "separator"), ("unknown.namespace:value", "namespace"),
            ("tool:%FF", "UTF-8"), ("tool:", "required"),
        )
        for key, message in cases:
            with self.subTest(key=key):
                with self.assertRaisesRegex(GraphKeyError, message):
                    parse_key(key)

        with self.assertRaisesRegex(GraphKeyError, "absolute"):
            file_key("/etc/hosts")
        with self.assertRaisesRegex(GraphKeyError, "escape"):
            file_key("../outside")
        with self.assertRaisesRegex(GraphKeyError, "path"):
            # Deliberately cross the typed API with an integer; retain runtime refusal.
            invalid_path = cast(str, 17)
            self.assertIs(type(invalid_path), int)
            graph_keys.file_key(invalid_path)
        wrong_type = validate_key(os.PathLike)
        self.assertFalse(wrong_type.valid)
        self.assertIsNotNone(wrong_type.error)
        self.assertIn("string", str(wrong_type.error))

    def test_result_serialization_sorts_records_and_counts_diagnostics(self):
        edge_key = canonical_edge_key(
            graph_key_version=1, source_key="file:bin/tool", kind="executes",
            target_key="tool:nix", identity_metadata={"b": 2, "a": 1},
        )
        graph = CanonicalGraph(
            graph_key_version=1,
            nodes=(
                CanonicalNode(
                    canonical_key="tool:nix", graph_key_version=1, kind="tool",
                    display_name="nix", metadata={}, confidence="heuristic", conflict=False,
                ),
                CanonicalNode(
                    canonical_key="file:bin/tool", graph_key_version=1, kind="file",
                    display_name="bin/tool", metadata={"role": "entrypoint"}, confidence="manual", conflict=False,
                ),
            ),
            edges=(
                CanonicalEdge(
                    edge_key=edge_key, graph_key_version=1, source_key="file:bin/tool",
                    kind="executes", target_key="tool:nix", identity_metadata={"a": 1, "b": 2},
                    metadata={"commands": ["nix"]}, confidence="heuristic", conflict=False,
                ),
            ),
            evidence=(
                CanonicalEvidence(
                    evidence_key="evidence:1", raw_observation_ordinal=1, raw_schema_version=1,
                    raw_kind="shell.command", raw_source_id="bin/tool#call:2:nix", path="bin/tool",
                    start_line=2, end_line=2, extractor="repo-shell", extractor_version="0.1.0",
                    confidence="manual", metadata={"raw": "nix flake check"},
                ),
                CanonicalEvidence(
                    evidence_key="evidence:0", raw_observation_ordinal=0, raw_schema_version=1,
                    raw_kind="file", raw_source_id="bin/tool", path="bin/tool",
                    start_line=None, end_line=None, extractor="repo-discovery",
                    extractor_version="0.1.0", confidence="manual", metadata={},
                ),
            ),
            node_evidence_links=(
                CanonicalNodeEvidenceLink(
                    canonical_key="tool:nix", evidence_key="evidence:1", link_kind="inferred_from_edge",
                ),
                CanonicalNodeEvidenceLink(
                    canonical_key="file:bin/tool", evidence_key="evidence:0", link_kind="observed",
                ),
            ),
            edge_evidence_links=(
                CanonicalEdgeEvidenceLink(
                    edge_key=edge_key, evidence_key="evidence:1", link_kind="supports",
                ),
            ),
            raw_observation_count=2,
        )
        result = CanonicalizationResult(
            graph=graph,
            diagnostics=(
                CanonicalizationDiagnostic(
                    severity="warning", category="dynamic_target",
                    message="dynamic target represented by placeholder",
                    raw_observation_ordinal=1, raw_source_id="bin/tool#call:2:nix",
                    path="bin/tool", field="target", value="$RUNNER",
                    placeholder_key="dynamic:tool:shell-variable-command",
                ),
                CanonicalizationDiagnostic(
                    severity="error", category="canonicalization_bug", message="edge references missing node",
                ),
            ),
        )
        payload = result.to_dict()

        self.assertFalse(result.ok)
        for k, v in [
            ("raw_observations", 2), ("nodes", 2), ("edges", 1), ("evidence", 2),
            ("node_evidence_links", 2), ("edge_evidence_links", 1), ("diagnostics", 2),
            ("errors", 1), ("warnings", 1), ("infos", 0),
        ]:
            self.assertEqual(payload["summary"][k], v)
        self.assertEqual(payload["nodes"][0]["canonical_key"], "file:bin/tool")
        self.assertEqual(payload["nodes"][1]["canonical_key"], "tool:nix")
        self.assertEqual(payload["evidence"][0]["evidence_key"], "evidence:0")
        self.assertEqual(payload["node_evidence_links"][0]["canonical_key"], "file:bin/tool")
        self.assertEqual(payload["diagnostics"][0]["severity"], "warning")
        self.assertEqual(payload["diagnostics"][1]["severity"], "error")
        self.assertEqual(result.to_json(), json.dumps(payload, indent=2, sort_keys=True) + "\n")

    def test_warning_only_result_is_ok(self):
        result = CanonicalizationResult(
            graph=CanonicalGraph.empty(raw_observation_count=1),
            diagnostics=(
                CanonicalizationDiagnostic(
                    severity="warning", category="unsupported_raw_observation_kind",
                    message="unsupported kind skipped", raw_observation_ordinal=0,
                ),
            ),
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.to_dict()["summary"]["warnings"], 1)

        for sev, cat, msg, err_pattern in [
            ("fatal", "bad", "bad severity", "severity"),
            ("error", "", "missing category", "category"),
            ("error", "bad", "", "message"),
        ]:
            with self.assertRaisesRegex(ValueError, err_pattern):
                CanonicalizationDiagnostic(severity=sev, category=cat, message=msg)

    def test_shell_command_dynamic_missing_and_bad_path_contracts(self):
        dynamic_result = canonicalize_observations([
            _obs("shell.command", "bin/tool#call:dynamic", "bin/tool",
                 target="dynamic:tool:shell-variable-command",
                 metadata={"dynamic_reason": "shell-variable-command"})
        ])
        missing_result = canonicalize_observations([
            _obs("shell.command", "bin/tool#call:missing", "bin/tool", metadata={})
        ])
        bad_path_result = canonicalize_observations([
            _obs("shell.command", "../outside#call:nix", "../outside", metadata={"command": "nix"})
        ])

        self.assertTrue(dynamic_result.ok)
        dynamic_payload = dynamic_result.to_dict()
        self.assertEqual(dynamic_payload["edges"][0]["target_key"], "dynamic:tool:shell-variable-command")
        self.assertEqual(dynamic_payload["diagnostics"][0]["category"], "dynamic_target")
        self.assertEqual(dynamic_payload["diagnostics"][0]["field"], "metadata.dynamic_reason")

        self.assertTrue(missing_result.ok)
        missing_payload = missing_result.to_dict()
        self.assertEqual(missing_payload["edges"][0]["target_key"], "unknown:tool:missing-command")
        self.assertEqual(missing_payload["diagnostics"][0]["category"], "missing_required_metadata")
        self.assertEqual(missing_payload["diagnostics"][0]["field"], "metadata.command")

        self.assertFalse(bad_path_result.ok)
        bad_path_payload = bad_path_result.to_dict()
        self.assertEqual(bad_path_payload["summary"]["edges"], 0)
        self.assertEqual(bad_path_payload["diagnostics"][0]["category"], "repo_escaping_path")

    def test_canonicalization_error_and_ambiguity_contracts(self):
        observations = [
            _obs("file", "../outside", "../outside", confidence="manual",
                 extractor="repo-discovery", metadata={"role": "source"}),
            _obs("shell.source", "../outside#source:common", "../outside", metadata={"resolved_path": "lib/common.sh"}),
            _obs("shell.source", "scripts/build.sh#source:unknown", "scripts/build.sh", metadata={"source": "$MAYBE"}),
            _obs("shell.env", "../outside#env:PATH", "../outside", metadata={"operation": "read", "variable": "PATH"}),
            _obs("shell.env", "scripts/build.sh#env:missing-operation", "scripts/build.sh", metadata={"variable": "PATH"}),
            _obs("shell.env", "scripts/build.sh#env:append", "scripts/build.sh", metadata={"operation": "append", "variable": "PATH"}),
            _obs("shell.env", "scripts/build.sh#env:secret", "scripts/build.sh", confidence="manual",
                 metadata={"operation": "write", "variable": "API_TOKEN", "value": "not-for-summary"}),
            _obs("shell.env", "scripts/build.sh#env:dynamic", "scripts/build.sh",
                 metadata={"operation": "read", "dynamic_reason": "parameter-expansion"}),
            _obs("shell.host_mutation", "../outside#host:brew", "../outside", metadata={"category": "package-management"}),
            _obs("shell.host_mutation", "scripts/maintain.sh#host:missing", "scripts/maintain.sh", metadata={"tool": "brew"}),
            _obs("shell.host_mutation", "scripts/maintain.sh#host:custom", "scripts/maintain.sh",
                 metadata={"category": "custom-host-change", "tool": "maintain", "argv": ["maintain", "host"],
                           "effective_argv": ["sudo", "maintain", "host"], "privileged": True, "reason": "fixture"}),
            _obs("shell.command", "bin/tool#call:target-dynamic", "bin/tool",
                 target="dynamic:tool:command-substitution", metadata={}),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()
        diagnostic_categories = [d["category"] for d in payload["diagnostics"]]
        edge_targets = {edge["target_key"] for edge in payload["edges"]}
        secret_edges = [edge for edge in payload["edges"] if edge["target_key"] == "env:API_TOKEN"]

        self.assertFalse(result.ok)
        self.assertGreaterEqual(payload["summary"]["diagnostics"], 10)
        for cat in (
            "repo_escaping_path", "unknown_target", "unsupported_operation",
            "secret_prone_value", "unregistered_category", "dynamic_target",
        ):
            self.assertIn(cat, diagnostic_categories)
        for target in (
            "unknown:file:unresolved-shell-source", "dynamic:env:parameter-expansion",
            "dynamic:tool:command-substitution", "unknown:host.category:missing-host-category",
            "unknown:host.category:unregistered-custom-host-change",
        ):
            self.assertIn(target, edge_targets)
        self.assertEqual(secret_edges[0]["metadata"]["value_redacted"], True)
        self.assertNotIn("values", secret_edges[0]["metadata"])
