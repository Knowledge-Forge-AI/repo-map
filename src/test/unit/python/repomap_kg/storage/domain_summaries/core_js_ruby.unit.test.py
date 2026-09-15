import unittest
import os
from types import SimpleNamespace
from unittest.mock import patch

from repomap_kg.storage import (
    StorageSchemaError,
    query_js_summary,
    query_js_framework_summary,
    query_ruby_summary,
    js_framework_summary_from_storage_payload,
    query_canonical_storage_summary,
)
from repomap_kg.storage.readback_driver import PG_CONNECTOR_ENV, READBACK_DRIVER_ENV

class StorageDomainCoreJsRubySummaryUnitTests(unittest.TestCase):
    def test_query_canonical_storage_summary_returns_counts(self):
        completed = SimpleNamespace(
            stdout=(
                '{"root_path":"/tmp/fixture",'
                '"repository_name":"fixture",'
                '"runs":1,"files":2,'
                '"raw_observations":4,'
                '"raw_observations_total":4,'
                '"latest_run_raw_observations":2,'
                '"canonical_nodes":6,'
                '"canonical_edges":7,'
                '"canonical_evidence":8}\n'
            )
        )

        with patch.dict(os.environ, {READBACK_DRIVER_ENV: "psql"}):
            with patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
                summary = query_canonical_storage_summary(
                    ["-d", "postgres"],
                    root_path="/tmp/fixture",
                    psql_command="/bin/psql",
                )

        self.assertEqual(summary.repository_name, "fixture")
        self.assertEqual(summary.raw_observations, 4)
        self.assertEqual(summary.raw_observations_total, 4)
        self.assertEqual(summary.latest_run_raw_observations, 2)
        self.assertEqual(summary.canonical_nodes, 6)
        self.assertEqual(summary.canonical_edges, 7)
        self.assertEqual(summary.canonical_evidence, 8)
        self.assertIn("-qAt", run.call_args.args[0])
        self.assertIn(
            "COUNT(*) FROM canonical_nodes",
            run.call_args.kwargs["input"],
        )
    def test_query_canonical_storage_summary_rejects_malformed_json(self):
        completed = SimpleNamespace(stdout='{"root_path": "/tmp/fixture"}\n')

        with patch("repomap_kg.storage.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(
                StorageSchemaError,
                "canonical storage summary",
            ):
                query_canonical_storage_summary(
                    ["-d", "postgres"],
                    root_path="/tmp/fixture",
                )
    def test_query_ruby_summary_returns_profile_counts(self):
        completed = SimpleNamespace(
            stdout=(
                '{"root_path":"/tmp/fixture",'
                '"repository_name":"fixture",'
                '"ruby_files":8,'
                '"modules":2,'
                '"classes":4,'
                '"methods":9,'
                '"singleton_methods":1,'
                '"constants":3,'
                '"routes":5,'
                '"test_cases":2,'
                '"test_methods":4,'
                '"references":12,'
                '"gem_dependencies":5,'
                '"vagrant_configs":6,'
                '"rake_tasks":3,'
                '"rake_namespaces":1,'
                '"dynamic_diagnostics":4,'
                '"parse_errors":0,'
                '"profile_counts":{'
                '"gemfile":1,'
                '"gemspec":1,'
                '"hanami":2,'
                '"minitest":2,'
                '"rake":1,'
                '"sinatra":1,'
                '"vagrantfile":1'
                '},'
                '"no_execution":true}\n'
            )
        )

        with patch.dict(os.environ, {PG_CONNECTOR_ENV: "psql"}), patch(
            "repomap_kg.storage.subprocess.run", return_value=completed
        ) as run:
            summary = query_ruby_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                psql_command="/bin/psql",
            )

        self.assertEqual(summary.repository_name, "fixture")
        self.assertEqual(summary.ruby_files, 8)
        self.assertEqual(summary.routes, 5)
        self.assertEqual(summary.test_methods, 4)
        self.assertEqual(summary.gem_dependencies, 5)
        self.assertEqual(summary.vagrant_configs, 6)
        self.assertEqual(summary.rake_tasks, 3)
        self.assertEqual(summary.dynamic_diagnostics, 4)
        self.assertEqual(summary.profile_counts["sinatra"], 1)
        self.assertTrue(summary.no_execution)
        self.assertIn("-qAt", run.call_args.args[0])
        self.assertIn("canonical_nodes.kind LIKE 'ruby.%'", run.call_args.kwargs["input"])
    def test_query_ruby_summary_rejects_malformed_json(self):
        completed = SimpleNamespace(stdout='{"root_path": "/tmp/fixture"}\n')

        with patch.dict(os.environ, {PG_CONNECTOR_ENV: "psql"}), patch(
            "repomap_kg.storage.subprocess.run", return_value=completed
        ):
            with self.assertRaisesRegex(StorageSchemaError, "ruby summary"):
                query_ruby_summary(["-d", "postgres"], root_path="/tmp/fixture")
    def test_query_js_summary_returns_profile_counts(self):
        completed = SimpleNamespace(
            stdout=(
                '{"root_path":"/tmp/fixture",'
                '"repository_name":"fixture",'
                '"js_files":12,'
                '"modules":12,'
                '"functions":6,'
                '"classes":3,'
                '"methods":2,'
                '"variables":8,'
                '"components":5,'
                '"routes":4,'
                '"test_suites":2,'
                '"test_cases":4,'
                '"references":19,'
                '"imports":10,'
                '"exports":9,'
                '"hooks":3,'
                '"test_expectations":4,'
                '"source_map_references":1,'
                '"frontend_asset_files":2,'
                '"saved_page_asset_files":1,'
                '"test_report_asset_files":1,'
                '"dynamic_diagnostics":6,'
                '"parse_errors":0,'
                '"profile_counts":{'
                '"angular":2,'
                '"generic_javascript":3,'
                '"jest":2,'
                '"react":3,'
                '"test_report_asset":1,'
                '"vue":1'
                '},'
                '"no_execution":true}\n'
            )
        )

        with patch.dict(os.environ, {PG_CONNECTOR_ENV: "psql"}), patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
            summary = query_js_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                psql_command="/bin/psql",
            )

        self.assertEqual(summary.repository_name, "fixture")
        self.assertEqual(summary.js_files, 12)
        self.assertEqual(summary.components, 5)
        self.assertEqual(summary.test_cases, 4)
        self.assertEqual(summary.source_map_references, 1)
        self.assertEqual(summary.frontend_asset_files, 2)
        self.assertEqual(summary.test_report_asset_files, 1)
        self.assertEqual(summary.dynamic_diagnostics, 6)
        self.assertEqual(summary.profile_counts["react"], 3)
        self.assertTrue(summary.no_execution)
        self.assertIn("-qAt", run.call_args.args[0])
        self.assertIn("canonical_nodes.kind LIKE 'js.%'", run.call_args.kwargs["input"])
    def test_query_js_summary_rejects_malformed_json(self):
        completed = SimpleNamespace(stdout='{"root_path": "/tmp/fixture"}\n')

        with patch.dict(os.environ, {PG_CONNECTOR_ENV: "psql"}), patch("repomap_kg.storage.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(StorageSchemaError, "js summary"):
                query_js_summary(["-d", "postgres"], root_path="/tmp/fixture")
    def test_query_js_framework_summary_returns_safe_counts(self):
        completed = SimpleNamespace(
            stdout=(
                '{"root_path":"/tmp/fixture",'
                '"repository_name":"fixture",'
                '"framework_observations":42,'
                '"framework_profiles":{'
                '"node":5,"express":8,"nest":6,"next":7,"jest":9,"jquery":7,'
                '"generic_js":4},'
                '"node":{"entrypoints":2,"requires":4,"exports":3,'
                '"env_references":2},'
                '"express":{"apps":1,"routers":1,"routes":6,"middleware":3,'
                '"error_handlers":1,"dynamic_routes":1},'
                '"nest":{"modules":1,"controllers":2,"providers":3,'
                '"routes":5,"decorators":12},'
                '"next":{"pages":3,"api_routes":1,"app_routes":2,'
                '"components":2,"route_handlers":1},'
                '"jest":{"suites":2,"tests":4,"expectations":6,"mocks":2},'
                '"jquery":{"selectors":4,"events":3,"ajax_references":2,'
                '"plugin_references":1},'
                '"generic_js":{"canonical_routes":6,"canonical_test_suites":2,'
                '"canonical_test_cases":4,"canonical_components":2},'
                '"diagnostics":{"framework_observation_limit":1,'
                '"framework_selector_limit":1},'
                '"safety":{"no_execution":true,"no_fetch":true,'
                '"raw_profile_only":true,"no_new_canonical_namespaces":true}}\n'
            )
        )

        with patch.dict(os.environ, {PG_CONNECTOR_ENV: "psql"}), patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
            summary = query_js_framework_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                psql_command="/bin/psql",
            )

        self.assertEqual(summary.repository_name, "fixture")
        self.assertEqual(summary.framework_observations, 42)
        self.assertEqual(summary.framework_profiles["express"], 8)
        self.assertEqual(summary.node["entrypoints"], 2)
        self.assertEqual(summary.express["dynamic_routes"], 1)
        self.assertEqual(summary.nest["decorators"], 12)
        self.assertEqual(summary.next["route_handlers"], 1)
        self.assertEqual(summary.jest["mocks"], 2)
        self.assertEqual(summary.jquery["ajax_references"], 2)
        self.assertEqual(summary.generic_js["canonical_routes"], 6)
        self.assertEqual(summary.diagnostics["framework_selector_limit"], 1)
        self.assertTrue(summary.safety["no_execution"])
        self.assertTrue(summary.safety["raw_profile_only"])
        self.assertIn("-qAt", run.call_args.args[0])
        self.assertIn("node.entrypoint", run.call_args.kwargs["input"])
        self.assertIn("js.framework_reference", run.call_args.kwargs["input"])
        self.assertIn("js.route", run.call_args.kwargs["input"])
    def test_query_js_framework_summary_rejects_malformed_json(self):
        completed = SimpleNamespace(stdout='{"root_path": "/tmp/fixture"}\n')

        with patch.dict(os.environ, {PG_CONNECTOR_ENV: "psql"}), patch("repomap_kg.storage.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(StorageSchemaError, "js framework summary"):
                query_js_framework_summary(["-d", "postgres"], root_path="/tmp/fixture")
    def test_js_framework_summary_empty_payload_keeps_safety_markers(self):
        summary = js_framework_summary_from_storage_payload(
            {
                "root_path": "/tmp/empty",
                "repository_name": None,
                "framework_observations": 0,
                "framework_profiles": {
                    "node": 0,
                    "express": 0,
                    "nest": 0,
                    "next": 0,
                    "jest": 0,
                    "jquery": 0,
                    "generic_js": 0,
                },
                "node": {
                    "entrypoints": 0,
                    "requires": 0,
                    "exports": 0,
                    "env_references": 0,
                },
                "express": {
                    "apps": 0,
                    "routers": 0,
                    "routes": 0,
                    "middleware": 0,
                    "error_handlers": 0,
                    "dynamic_routes": 0,
                },
                "nest": {
                    "modules": 0,
                    "controllers": 0,
                    "providers": 0,
                    "routes": 0,
                    "decorators": 0,
                },
                "next": {
                    "pages": 0,
                    "api_routes": 0,
                    "app_routes": 0,
                    "components": 0,
                    "route_handlers": 0,
                },
                "jest": {
                    "suites": 0,
                    "tests": 0,
                    "expectations": 0,
                    "mocks": 0,
                },
                "jquery": {
                    "selectors": 0,
                    "events": 0,
                    "ajax_references": 0,
                    "plugin_references": 0,
                },
                "generic_js": {
                    "canonical_routes": 0,
                    "canonical_test_suites": 0,
                    "canonical_test_cases": 0,
                    "canonical_components": 0,
                },
                "diagnostics": {
                    "framework_observation_limit": 0,
                    "framework_selector_limit": 0,
                },
                "safety": {
                    "no_execution": True,
                    "no_fetch": True,
                    "raw_profile_only": True,
                    "no_new_canonical_namespaces": True,
                },
            }
        )

        self.assertEqual(summary.repository_name, None)
        self.assertEqual(summary.framework_observations, 0)
        self.assertEqual(summary.framework_profiles["node"], 0)
        self.assertEqual(summary.generic_js["canonical_routes"], 0)
        self.assertTrue(summary.safety["no_execution"])
        self.assertTrue(summary.safety["no_new_canonical_namespaces"])
