import unittest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repomap_kg.canonicalization.main import canonicalize_observations
    from repomap_kg.observations.raw import RawObservation
else:
    from repomap_kg.canonicalization import canonicalize_observations
    from repomap_kg.observations import RawObservation

from repomap_kg.canonicalization.records import canonical_edge_key
from repomap_kg.graph.keys import (
    js_class_key,
    js_component_key,
    js_file_key,
    js_function_key,
    js_method_key,
    js_module_key,
    js_route_key,
    js_test_case_key,
    js_test_suite_key,
    js_variable_key,
)


class CanonicalizationJavaScriptLanguageFamilyUnitTests(unittest.TestCase):
    def test_js_definitions_create_generic_defines_edges(self):
        suite_key = js_test_suite_key("src/jest/example.test.js", "/tests/describe[1]")
        observations = [
            RawObservation(
                kind="js.file",
                source_id="src/index.js#js-file",
                path="src/index.js",
                start_line=1,
                end_line=20,
                name="src/index.js",
                target=js_file_key("src/index.js"),
                confidence="extracted",
                extractor="repo-js",
                extractor_version="0.1.0",
                metadata={
                    "format": "javascript",
                    "profile": "react",
                    "parser": "stdlib-js-lexical",
                },
            ),
            RawObservation(
                kind="js.module",
                source_id="src/index.js#js-module",
                path="src/index.js",
                start_line=1,
                end_line=1,
                name="src/index.js",
                target=js_module_key("src/index.js"),
                confidence="extracted",
                extractor="repo-js",
                extractor_version="0.1.0",
                metadata={
                    "format": "javascript",
                    "profile": "react",
                    "parser": "stdlib-js-lexical",
                    "module_system": "esm",
                },
            ),
            RawObservation(
                kind="js.function",
                source_id="src/index.js#js-function:main",
                path="src/index.js",
                start_line=2,
                end_line=2,
                name="main",
                target=js_function_key("src/index.js", "main"),
                confidence="extracted",
                extractor="repo-js",
                extractor_version="0.1.0",
                metadata={
                    "function_name": "main",
                    "profile": "react",
                    "source_key": js_module_key("src/index.js"),
                },
            ),
            RawObservation(
                kind="js.class",
                source_id="src/index.js#js-class:Runner",
                path="src/index.js",
                start_line=5,
                end_line=5,
                name="Runner",
                target=js_class_key("src/index.js", "Runner"),
                confidence="extracted",
                extractor="repo-js",
                extractor_version="0.1.0",
                metadata={
                    "class_name": "Runner",
                    "profile": "react",
                    "source_key": js_module_key("src/index.js"),
                },
            ),
            RawObservation(
                kind="js.method",
                source_id="src/index.js#js-method:Runner:start",
                path="src/index.js",
                start_line=6,
                end_line=6,
                name="start",
                target=js_method_key(js_class_key("src/index.js", "Runner"), "start"),
                confidence="extracted",
                extractor="repo-js",
                extractor_version="0.1.0",
                metadata={
                    "method_name": "start",
                    "class_key": js_class_key("src/index.js", "Runner"),
                    "profile": "react",
                },
            ),
            RawObservation(
                kind="js.variable",
                source_id="src/index.js#js-variable:COUNT",
                path="src/index.js",
                start_line=10,
                end_line=10,
                name="COUNT",
                target=js_variable_key("src/index.js", "COUNT"),
                confidence="extracted",
                extractor="repo-js",
                extractor_version="0.1.0",
                metadata={
                    "local_name": "COUNT",
                    "literal_type": "integer",
                    "profile": "react",
                    "source_key": js_module_key("src/index.js"),
                },
            ),
            RawObservation(
                kind="js.component",
                source_id="src/index.js#js-component:App",
                path="src/index.js",
                start_line=12,
                end_line=12,
                name="App",
                target=js_component_key("src/index.js", "App"),
                confidence="extracted",
                extractor="repo-js",
                extractor_version="0.1.0",
                metadata={
                    "component_name": "App",
                    "profile": "react",
                    "source_key": js_module_key("src/index.js"),
                },
            ),
            RawObservation(
                kind="js.test_suite",
                source_id="src/jest/example.test.js#js-suite:describe-1",
                path="src/jest/example.test.js",
                start_line=2,
                end_line=2,
                name="describe[1]",
                target=suite_key,
                confidence="extracted",
                extractor="repo-js",
                extractor_version="0.1.0",
                metadata={
                    "test_framework": "jest",
                    "profile": "jest",
                    "test_pointer": "/tests/describe[1]",
                },
            ),
            RawObservation(
                kind="js.test_case",
                source_id="src/jest/example.test.js#js-test:test-1",
                path="src/jest/example.test.js",
                start_line=3,
                end_line=3,
                name="test[1]",
                target=js_test_case_key(suite_key, "/tests/describe[1]/test[1]"),
                confidence="extracted",
                extractor="repo-js",
                extractor_version="0.1.0",
                metadata={
                    "test_framework": "jest",
                    "profile": "jest",
                    "test_suite_key": suite_key,
                    "test_pointer": "/tests/describe[1]/test[1]",
                },
            ),
            RawObservation(
                kind="js.route",
                source_id="src/react/App.jsx#js-route:/home",
                path="src/react/App.jsx",
                start_line=4,
                end_line=4,
                name="/home",
                target=js_route_key("src/react/App.jsx", "/routes/path:/home"),
                confidence="extracted",
                extractor="repo-js",
                extractor_version="0.1.0",
                metadata={
                    "route_pattern": "/home",
                    "profile": "react",
                    "route_pointer": "/routes/path:/home",
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()
        edges = {
            (edge["kind"], edge["source_key"], edge["target_key"])
            for edge in payload["edges"]
        }

        self.assertTrue(result.ok)
        self.assertEqual(payload["diagnostics"], [])
        self.assertIn(
            "js.file:file%3Asrc%2Findex.js",
            {node["canonical_key"] for node in payload["nodes"]},
        )
        self.assertIn(
            (
                "defines",
                "js.module:file%3Asrc%2Findex.js",
                "js.function:file%3Asrc%2Findex.js:main",
            ),
            edges,
        )
        self.assertIn(
            (
                "defines",
                "js.class:file%3Asrc%2Findex.js:Runner",
                "js.method:js.class%3Afile%253Asrc%252Findex.js%3ARunner:start",
            ),
            edges,
        )
        self.assertIn(
            (
                "defines",
                suite_key,
                js_test_case_key(suite_key, "/tests/describe[1]/test[1]"),
            ),
            edges,
        )
        self.assertIn(
            (
                "defines",
                "js.module:file%3Asrc%2Freact%2FApp.jsx",
                "js.route:file%3Asrc%2Freact%2FApp.jsx:%2Froutes%2Fpath%3A%2Fhome",
            ),
            edges,
        )

    def test_js_reference_creates_references_edge_and_parse_errors_are_raw_only(self):
        observation = RawObservation(
            kind="js.reference",
            source_id="src/index.js#js-reference:import:1",
            path="src/index.js",
            start_line=1,
            end_line=1,
            name="./util.mjs",
            target="file:src/util.mjs",
            confidence="extracted",
            extractor="repo-js",
            extractor_version="0.1.0",
            metadata={
                "source_key": js_module_key("src/index.js"),
                "reference_kind": "import",
                "raw_value_summary": "./util.mjs",
                "resolution_reason": "repo-local",
                "profile": "generic_javascript",
            },
        )
        parse_error = RawObservation(
            kind="js.parse_error",
            source_id="src/index.js#js-diagnostic:dynamic-import:2",
            path="src/index.js",
            start_line=2,
            end_line=2,
            confidence="heuristic",
            extractor="repo-js",
            extractor_version="0.1.0",
            metadata={
                "error_kind": "dynamic-import",
                "dynamic": True,
                "dynamic_reason": "template-literal-import",
            },
        )
        edge_key = canonical_edge_key(
            graph_key_version=1,
            source_key=js_module_key("src/index.js"),
            kind="references",
            target_key="file:src/util.mjs",
            identity_metadata={},
        )

        result = canonicalize_observations([observation, parse_error])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["evidence"], 2)
        self.assertEqual(payload["summary"]["nodes"], 2)
        self.assertEqual(payload["summary"]["edges"], 1)
        self.assertEqual(payload["edges"][0]["edge_key"], edge_key)
        self.assertEqual(payload["evidence"][1]["raw_kind"], "js.parse_error")

    def test_js5_framework_profile_observations_are_evidence_only(self):
        framework_kinds = (
            "js.framework_profile",
            "js.runtime_profile",
            "js.package_context",
            "js.route_handler",
            "js.middleware",
            "js.controller",
            "js.provider",
            "js.module_binding",
            "js.test_config",
            "js.dom_selector",
            "js.dom_event",
            "js.ajax_reference",
            "js.server_entrypoint",
            "js.client_entrypoint",
            "js.framework_reference",
            "node.entrypoint",
            "node.export",
            "node.require",
            "express.app",
            "express.router",
            "express.route",
            "express.middleware",
            "express.error_handler",
            "nest.module",
            "nest.controller",
            "nest.provider",
            "nest.route",
            "nest.decorator",
            "next.route",
            "next.page",
            "next.api_route",
            "next.app_route",
            "next.component",
            "jest.suite",
            "jest.test",
            "jest.expectation",
            "jest.mock",
            "jquery.selector",
            "jquery.event",
            "jquery.ajax",
            "jquery.plugin_reference",
        )
        observations = [
            RawObservation(
                kind=kind,
                source_id=f"src/app.js#{kind}:1",
                path="src/app.js",
                start_line=1,
                end_line=1,
                name=kind,
                confidence="extracted",
                extractor="repo-js",
                extractor_version="0.1.0",
                metadata={
                    "profile": kind.split(".", 1)[0],
                    "source_key": js_module_key("src/app.js"),
                },
            )
            for kind in framework_kinds
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(payload["summary"]["raw_observations"], len(framework_kinds))
        self.assertEqual(payload["summary"]["evidence"], len(framework_kinds))
        self.assertEqual(payload["summary"]["nodes"], 0)
        self.assertEqual(payload["summary"]["edges"], 0)
