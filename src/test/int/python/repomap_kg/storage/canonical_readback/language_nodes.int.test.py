import json
import unittest

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    query_canonical_edge_explanation,
    query_canonical_edge_records,
    query_canonical_node_records,
    query_js_summary,
    query_ruby_summary,
)

from repomap_test_support.storage_integration import (
    canonicalization_fixture,
)


class StorageCanonicalLanguageNodeReadbackIntegrationTests(unittest.TestCase):
    def test_storage_load_files_reads_ruby_nodes_references_and_explain(self):
        require_postgres_binaries()
        raw_jsonl = canonicalization_fixture("ruby_basic", "raw_observations.jsonl")
        root_path = "/tmp/ruby-fixture"

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            exit_code, _stdout, stderr = run_repo_map_in_process(
                "storage",
                "load-files",
                str(raw_jsonl),
                "--repository-name",
                "ruby-fixture",
                "--root-path",
                root_path,
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                postgres.database,
                "--psql-command",
                postgres.psql_command,
                "--json",
            )

            ruby_files = query_canonical_node_records(
                postgres.psql_args,
                root_path=root_path,
                kind="ruby.file",
                psql_command=postgres.psql_command,
            )
            ruby_classes = query_canonical_node_records(
                postgres.psql_args,
                root_path=root_path,
                kind="ruby.class",
                canonical_key="ruby.class:Example%3A%3ARunner",
                psql_command=postgres.psql_command,
            )
            routes = query_canonical_node_records(
                postgres.psql_args,
                root_path=root_path,
                kind="ruby.route",
                psql_command=postgres.psql_command,
            )
            references = query_canonical_edge_records(
                postgres.psql_args,
                root_path=root_path,
                kind="references",
                source_key="ruby.file:file%3Alib%2Fexample.rb",
                target_key="file:lib/example/service.rb",
                psql_command=postgres.psql_command,
            )
            explanation = query_canonical_edge_explanation(
                postgres.psql_args,
                root_path=root_path,
                source_key=references[0].source_key,
                kind=references[0].edge_kind,
                target_key=references[0].target_key,
                identity_metadata_hash=references[0].identity_metadata_hash,
                psql_command=postgres.psql_command,
            )
            ruby_summary = query_ruby_summary(
                postgres.psql_args,
                root_path=root_path,
                psql_command=postgres.psql_command,
            )
            summary_exit_code, summary_stdout, summary_stderr = (
                run_repo_map_in_process(
                    "storage",
                    "ruby-summary",
                    "--root-path",
                    root_path,
                    "--pg-host",
                    str(postgres.socket_dir),
                    "--pg-port",
                    str(postgres.port),
                    "--pg-user",
                    postgres.user,
                    "--pg-database",
                    postgres.database,
                    "--psql-command",
                    postgres.psql_command,
                    "--json",
                )
            )

        self.assertEqual(exit_code, 0, stderr)
        self.assertEqual(summary_exit_code, 0, summary_stderr)
        self.assertGreaterEqual(len(ruby_files), 10)
        self.assertEqual(
            [node.canonical_key for node in ruby_classes],
            ["ruby.class:Example%3A%3ARunner"],
        )
        self.assertTrue(
            any(node.canonical_key.startswith("ruby.route:") for node in routes)
        )
        self.assertEqual(len(references), 1)
        self.assertEqual(references[0].edge_kind, "references")
        self.assertIsNotNone(explanation.edge)
        assert explanation.edge is not None
        self.assertEqual(explanation.edge.source_key, "ruby.file:file%3Alib%2Fexample.rb")
        self.assertGreaterEqual(ruby_summary.ruby_files, 10)
        self.assertGreaterEqual(ruby_summary.routes, 2)
        self.assertGreaterEqual(ruby_summary.test_methods, 1)
        self.assertGreaterEqual(ruby_summary.gem_dependencies, 4)
        self.assertGreaterEqual(ruby_summary.vagrant_configs, 5)
        self.assertGreaterEqual(ruby_summary.rake_tasks, 2)
        self.assertEqual(ruby_summary.profile_counts["sinatra"], 1)
        self.assertEqual(ruby_summary.profile_counts["vagrantfile"], 1)
        self.assertTrue(ruby_summary.no_execution)
        summary_payload = json.loads(summary_stdout)
        self.assertEqual(summary_payload["ruby_files"], ruby_summary.ruby_files)
        self.assertEqual(summary_payload["routes"], ruby_summary.routes)
        self.assertEqual(
            summary_payload["profile_counts"]["sinatra"],
            ruby_summary.profile_counts["sinatra"],
        )
        self.assertTrue(summary_payload["no_execution"])
        readback_payload = "\n".join(
            (
                *(str(node.to_dict()) for node in ruby_files),
                *(str(node.to_dict()) for node in ruby_classes),
                *(str(node.to_dict()) for node in routes),
                *(str(edge.to_dict()) for edge in references),
                str(explanation.to_dict()),
                str(ruby_summary.to_dict()),
                summary_stdout,
            )
        )
        self.assertNotIn("EXAMPLE_API_KEY", readback_payload)
        self.assertNotIn("EXAMPLE_SESSION_SECRET", readback_payload)
    def test_storage_load_files_reads_js_nodes_references_and_explain(self):
        require_postgres_binaries()
        raw_jsonl = canonicalization_fixture("js_basic", "raw_observations.jsonl")
        root_path = "/tmp/js-fixture"

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            exit_code, _stdout, stderr = run_repo_map_in_process(
                "storage",
                "load-files",
                str(raw_jsonl),
                "--repository-name",
                "js-fixture",
                "--root-path",
                root_path,
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                postgres.database,
                "--psql-command",
                postgres.psql_command,
                "--json",
            )

            js_files = query_canonical_node_records(
                postgres.psql_args,
                root_path=root_path,
                kind="js.file",
                psql_command=postgres.psql_command,
            )
            js_classes = query_canonical_node_records(
                postgres.psql_args,
                root_path=root_path,
                kind="js.class",
                canonical_key="js.class:file%3Asrc%2Findex.js:Runner",
                psql_command=postgres.psql_command,
            )
            components = query_canonical_node_records(
                postgres.psql_args,
                root_path=root_path,
                kind="js.component",
                psql_command=postgres.psql_command,
            )
            routes = query_canonical_node_records(
                postgres.psql_args,
                root_path=root_path,
                kind="js.route",
                psql_command=postgres.psql_command,
            )
            references = query_canonical_edge_records(
                postgres.psql_args,
                root_path=root_path,
                kind="references",
                source_key="js.module:file%3Asrc%2Findex.js",
                target_key="file:src/util.mjs",
                psql_command=postgres.psql_command,
            )
            explanation = query_canonical_edge_explanation(
                postgres.psql_args,
                root_path=root_path,
                source_key=references[0].source_key,
                kind=references[0].edge_kind,
                target_key=references[0].target_key,
                identity_metadata_hash=references[0].identity_metadata_hash,
                psql_command=postgres.psql_command,
            )
            js_summary = query_js_summary(
                postgres.psql_args,
                root_path=root_path,
                psql_command=postgres.psql_command,
            )
            summary_exit_code, summary_stdout, summary_stderr = (
                run_repo_map_in_process(
                    "storage",
                    "js-summary",
                    "--root-path",
                    root_path,
                    "--pg-host",
                    str(postgres.socket_dir),
                    "--pg-port",
                    str(postgres.port),
                    "--pg-user",
                    postgres.user,
                    "--pg-database",
                    postgres.database,
                    "--psql-command",
                    postgres.psql_command,
                    "--json",
                )
            )
            table_exit_code, table_stdout, table_stderr = run_repo_map_in_process(
                "storage",
                "js-summary",
                "--root-path",
                root_path,
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                postgres.database,
                "--psql-command",
                postgres.psql_command,
            )

        self.assertEqual(exit_code, 0, stderr)
        self.assertEqual(summary_exit_code, 0, summary_stderr)
        self.assertEqual(table_exit_code, 0, table_stderr)
        self.assertGreaterEqual(len(js_files), 10)
        self.assertEqual(
            [node.canonical_key for node in js_classes],
            ["js.class:file%3Asrc%2Findex.js:Runner"],
        )
        self.assertTrue(
            any(node.canonical_key.startswith("js.component:") for node in components)
        )
        self.assertTrue(any(node.canonical_key.startswith("js.route:") for node in routes))
        self.assertEqual(len(references), 1)
        self.assertEqual(references[0].edge_kind, "references")
        self.assertIsNotNone(explanation.edge)
        assert explanation.edge is not None
        self.assertEqual(explanation.edge.source_key, "js.module:file%3Asrc%2Findex.js")
        self.assertGreaterEqual(js_summary.js_files, 10)
        self.assertGreaterEqual(js_summary.components, 5)
        self.assertGreaterEqual(js_summary.routes, 2)
        self.assertGreaterEqual(js_summary.test_suites, 2)
        self.assertGreaterEqual(js_summary.test_cases, 2)
        self.assertGreaterEqual(js_summary.hooks, 2)
        self.assertGreaterEqual(js_summary.test_expectations, 2)
        self.assertGreaterEqual(js_summary.source_map_references, 1)
        self.assertGreaterEqual(js_summary.dynamic_diagnostics, 5)
        self.assertEqual(js_summary.profile_counts["jest"], 2)
        self.assertGreaterEqual(js_summary.profile_counts["react"], 4)
        self.assertEqual(js_summary.profile_counts["angular"], 2)
        self.assertEqual(js_summary.profile_counts["vue"], 1)
        self.assertEqual(js_summary.profile_counts["test_report_asset"], 1)
        self.assertEqual(js_summary.test_report_asset_files, 1)
        self.assertTrue(js_summary.no_execution)
        summary_payload = json.loads(summary_stdout)
        self.assertEqual(summary_payload["js_files"], js_summary.js_files)
        self.assertEqual(summary_payload["components"], js_summary.components)
        self.assertEqual(
            summary_payload["profile_counts"]["react"],
            js_summary.profile_counts["react"],
        )
        self.assertTrue(summary_payload["no_execution"])
        self.assertIn("js_files", table_stdout)
        self.assertIn("profile_counts", table_stdout)
        self.assertIn("react=", table_stdout)
        self.assertIn("no_execution", table_stdout)
        readback_payload = "\n".join(
            (
                *(str(node.to_dict()) for node in js_files),
                *(str(node.to_dict()) for node in js_classes),
                *(str(node.to_dict()) for node in components),
                *(str(node.to_dict()) for node in routes),
                *(str(edge.to_dict()) for edge in references),
                str(explanation.to_dict()),
                str(js_summary.to_dict()),
                summary_stdout,
                table_stdout,
            )
        )
        self.assertNotIn("placeholder", readback_payload)
        self.assertNotIn("Bearer ${apiToken}", readback_payload)
