import json
import tempfile
import unittest

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    query_canonical_edge_records,
    query_canonical_node_records,
    query_js_summary,
)

from repomap_test_support.storage_integration import (
    discovery_fixture,
)


class StorageCanonicalJsFrameworkReadbackIntegrationTests(unittest.TestCase):
    def test_storage_loads_js5_framework_observations_as_raw_evidence(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("js5_frameworks")

        discover_exit_code, discover_stdout, discover_stderr = (
            run_repo_map_in_process(
                "discover",
                str(fixture_root),
                "--jsonl",
            )
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as jsonl_file:
            jsonl_file.write(discover_stdout)
            jsonl_file.flush()

            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                storage_args = (
                    "--root-path",
                    str(fixture_root),
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
                load_exit_code, _load_stdout, load_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "load-files",
                        jsonl_file.name,
                        "--repository-name",
                        "js5-fixture",
                        *storage_args,
                        "--json",
                    )
                )
                raw_kinds_json = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json->>'kind' ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                )
                raw_payload = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                )
                canonical_nodes = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )
                canonical_edges = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )
                js_summary = query_js_summary(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        discovered_kinds = {record["kind"] for record in discovered}
        expected_framework_kinds = {
            "node.entrypoint",
            "node.require",
            "node.export",
            "express.app",
            "express.router",
            "express.route",
            "express.middleware",
            "express.error_handler",
            "nest.module",
            "nest.controller",
            "nest.provider",
            "nest.route",
            "next.page",
            "next.api_route",
            "next.app_route",
            "next.route",
            "jest.suite",
            "jest.test",
            "jest.expectation",
            "jest.mock",
            "jquery.selector",
            "jquery.event",
            "jquery.ajax",
            "jquery.plugin_reference",
            "js.framework_reference",
        }
        self.assertTrue(expected_framework_kinds.issubset(discovered_kinds))
        self.assertNotIn("fake-js5-jquery-token", discover_stdout)
        self.assertNotIn("SECRET_TOKEN", discover_stdout)

        self.assertEqual(load_exit_code, 0, load_stderr)
        raw_kinds = set(json.loads(raw_kinds_json))
        self.assertTrue(expected_framework_kinds.issubset(raw_kinds))
        self.assertNotIn("fake-js5-jquery-token", raw_payload)
        self.assertNotIn("SECRET_TOKEN", raw_payload)
        canonical_kinds = {node.kind for node in canonical_nodes}
        self.assertIn("js.file", canonical_kinds)
        self.assertIn("js.route", canonical_kinds)
        self.assertFalse(
            any(
                node.kind.startswith(
                    ("express.", "nest.", "next.", "jest.", "jquery.", "node.")
                )
                for node in canonical_nodes
            )
        )
        self.assertEqual(
            {edge.edge_kind for edge in canonical_edges} - {"defines", "references"},
            set(),
        )
        self.assertGreaterEqual(js_summary.js_files, 8)
        self.assertGreaterEqual(js_summary.routes, 1)
        self.assertGreaterEqual(js_summary.test_cases, 1)
    def test_storage_js_framework_summary_reads_js5_evidence_without_reload(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("js5_frameworks")

        discover_exit_code, discover_stdout, discover_stderr = (
            run_repo_map_in_process(
                "discover",
                str(fixture_root),
                "--jsonl",
            )
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as jsonl_file:
            jsonl_file.write(discover_stdout)
            jsonl_file.flush()

            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                storage_args = (
                    "--root-path",
                    str(fixture_root),
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
                load_exit_code, _load_stdout, load_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "load-files",
                        jsonl_file.name,
                        "--repository-name",
                        "js6-fixture",
                        *storage_args,
                        "--json",
                    )
                )
                raw_count_before = postgres.psql_scalar(
                    "SELECT COUNT(*)::text FROM raw_observations;"
                )
                summary_exit_code, summary_stdout, summary_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "js-framework-summary",
                        *storage_args,
                        "--json",
                    )
                )
                table_exit_code, table_stdout, table_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "js-framework-summary",
                        *storage_args,
                    )
                )
                raw_count_after = postgres.psql_scalar(
                    "SELECT COUNT(*)::text FROM raw_observations;"
                )
                canonical_nodes = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )
                canonical_edges = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        self.assertEqual(load_exit_code, 0, load_stderr)
        self.assertEqual(summary_exit_code, 0, summary_stderr)
        self.assertEqual(table_exit_code, 0, table_stderr)
        self.assertEqual(raw_count_before, raw_count_after)
        payload = json.loads(summary_stdout)
        self.assertEqual(payload["repository_name"], "js6-fixture")
        self.assertGreaterEqual(payload["framework_observations"], 25)
        self.assertGreaterEqual(payload["framework_profiles"]["node"], 1)
        self.assertGreaterEqual(payload["framework_profiles"]["express"], 1)
        self.assertGreaterEqual(payload["framework_profiles"]["nest"], 1)
        self.assertGreaterEqual(payload["framework_profiles"]["next"], 1)
        self.assertGreaterEqual(payload["framework_profiles"]["jest"], 1)
        self.assertGreaterEqual(payload["framework_profiles"]["jquery"], 1)
        self.assertEqual(payload["node"]["entrypoints"], 1)
        self.assertGreaterEqual(payload["node"]["requires"], 1)
        self.assertEqual(payload["express"]["apps"], 1)
        self.assertGreaterEqual(payload["express"]["routes"], 4)
        self.assertEqual(payload["express"]["error_handlers"], 1)
        self.assertGreaterEqual(payload["express"]["dynamic_routes"], 1)
        self.assertEqual(payload["nest"]["modules"], 1)
        self.assertEqual(payload["nest"]["controllers"], 1)
        self.assertEqual(payload["nest"]["providers"], 1)
        self.assertGreaterEqual(payload["nest"]["routes"], 2)
        self.assertGreaterEqual(payload["next"]["pages"], 2)
        self.assertEqual(payload["next"]["api_routes"], 1)
        self.assertEqual(payload["next"]["app_routes"], 1)
        self.assertGreaterEqual(payload["next"]["route_handlers"], 2)
        self.assertEqual(payload["jest"]["suites"], 1)
        self.assertEqual(payload["jest"]["tests"], 1)
        self.assertEqual(payload["jest"]["expectations"], 2)
        self.assertGreaterEqual(payload["jest"]["mocks"], 3)
        self.assertEqual(payload["jquery"]["selectors"], 2)
        self.assertEqual(payload["jquery"]["events"], 3)
        self.assertEqual(payload["jquery"]["ajax_references"], 2)
        self.assertEqual(payload["jquery"]["plugin_references"], 1)
        self.assertGreaterEqual(payload["generic_js"]["canonical_routes"], 1)
        self.assertGreaterEqual(payload["generic_js"]["canonical_test_cases"], 1)
        self.assertTrue(payload["safety"]["no_execution"])
        self.assertTrue(payload["safety"]["no_fetch"])
        self.assertTrue(payload["safety"]["raw_profile_only"])
        self.assertTrue(payload["safety"]["no_new_canonical_namespaces"])
        self.assertIn("framework_observations", table_stdout)
        self.assertIn("entrypoints=1", table_stdout)
        self.assertIn("no_fetch=true", table_stdout)
        readback_payload = "\n".join((summary_stdout, table_stdout))
        self.assertNotIn("fake-js5-jquery-token", readback_payload)
        self.assertNotIn("SECRET_TOKEN", readback_payload)
        self.assertFalse(
            any(
                node.kind.startswith(
                    ("express.", "nest.", "next.", "jest.", "jquery.", "node.")
                )
                for node in canonical_nodes
            )
        )
        self.assertEqual(
            {edge.edge_kind for edge in canonical_edges} - {"defines", "references"},
            set(),
        )
