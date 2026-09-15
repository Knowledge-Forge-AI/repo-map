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
    query_openapi_summary,
)

from repomap_test_support.storage_integration import (
    openapi_fixture,
)


class StorageOpenApiReadbackIntegrationTests(unittest.TestCase):
    def test_storage_loads_openapi_profile_observations_as_raw_evidence(self):
        require_postgres_binaries()
        fixture_root = openapi_fixture("openapi1_contracts")

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
                        "openapi-contract-fixture",
                        *storage_args,
                        "--json",
                    )
                )
                raw_openapi_payload = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json ORDER BY ordinal)::text, '[]')
FROM raw_observations
WHERE payload_json->>'kind' LIKE 'openapi.%';
"""
                )
                config_documents = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    kind="config.document",
                    psql_command=postgres.psql_command,
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
        self.assertNotIn("fake-openapi-json-password", discover_stdout)
        self.assertNotIn("fake-openapi-json-token", discover_stdout)
        self.assertNotIn("fake-openapi-json-server-secret", discover_stdout)
        self.assertNotIn("fake-openapi-yaml-secret", discover_stdout)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        discovered_kinds = {record["kind"] for record in discovered}
        self.assertTrue(
            {
                "config.document",
                "config.path",
                "config.reference",
                "config.parse_error",
                "openapi.document",
                "openapi.info",
                "openapi.path",
                "openapi.operation",
                "openapi.response",
                "openapi.schema",
                "openapi.component",
                "openapi.reference",
                "openapi.security_scheme",
                "openapi.redaction",
                "openapi.parse_error",
            }.issubset(discovered_kinds)
        )

        self.assertEqual(load_exit_code, 0, load_stderr)
        raw_openapi = json.loads(raw_openapi_payload)
        raw_payload_text = json.dumps(raw_openapi, sort_keys=True)
        raw_kinds = {record["kind"] for record in raw_openapi}
        spec_families = {
            record.get("metadata", {}).get("spec_family")
            for record in raw_openapi
            if record["kind"] == "openapi.document"
        }
        self.assertIn("openapi3", spec_families)
        self.assertIn("swagger2", spec_families)
        self.assertIn("openapi.reference", raw_kinds)
        self.assertTrue(
            any(
                record.get("metadata", {}).get("reference_scope") == "remote"
                and record.get("metadata", {}).get("not_fetched")
                for record in raw_openapi
            )
        )
        self.assertNotIn("fake-openapi-json-password", raw_payload_text)
        self.assertNotIn("fake-openapi-json-token", raw_payload_text)
        self.assertNotIn("fake-openapi-json-server-secret", raw_payload_text)
        self.assertNotIn("fake-openapi-yaml-secret", raw_payload_text)

        document_keys = {record.canonical_key for record in config_documents}
        self.assertIn("config.document:file%3Aopenapi.json", document_keys)
        self.assertIn("config.document:file%3Aservice.openapi.yaml", document_keys)
        self.assertFalse(
            any(record.kind.startswith("openapi.") for record in canonical_nodes)
        )
        self.assertLessEqual(
            {edge.edge_kind for edge in canonical_edges},
            {"defines", "references"},
        )

    def test_storage_openapi_summary_reads_contract_evidence_without_reload(self):
        require_postgres_binaries()
        fixture_root = openapi_fixture("openapi1_contracts")

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
                        "openapi2-fixture",
                        *storage_args,
                        "--json",
                    )
                )
                raw_count_before = postgres.psql_scalar(
                    "SELECT COUNT(*)::text FROM raw_observations;"
                )
                summary = query_openapi_summary(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )
                summary_exit_code, summary_stdout, summary_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "openapi-summary",
                        *storage_args,
                        "--json",
                    )
                )
                table_exit_code, table_stdout, table_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "openapi-summary",
                        *storage_args,
                    )
                )
                raw_count_after = postgres.psql_scalar(
                    "SELECT COUNT(*)::text FROM raw_observations;"
                )
                config_documents = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    kind="config.document",
                    psql_command=postgres.psql_command,
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
        self.assertEqual(payload["repository_name"], "openapi2-fixture")
        self.assertEqual(payload["openapi_documents"], 4)
        self.assertEqual(payload["spec_families"]["openapi3"], 2)
        self.assertEqual(payload["spec_families"]["swagger2"], 2)
        self.assertEqual(summary.openapi_documents, 4)
        self.assertEqual(summary.spec_families["openapi3"], 2)
        self.assertGreaterEqual(payload["openapi_observations"], 20)
        self.assertGreaterEqual(payload["openapi"]["paths"], 1)
        self.assertGreaterEqual(payload["openapi"]["operations"], 1)
        self.assertGreaterEqual(payload["openapi"]["responses"], 1)
        self.assertGreaterEqual(payload["openapi"]["schemas"], 1)
        self.assertGreaterEqual(payload["openapi"]["components"], 1)
        self.assertGreaterEqual(payload["openapi"]["security_schemes"], 1)
        self.assertGreaterEqual(payload["openapi"]["examples"], 1)
        self.assertGreaterEqual(payload["methods"]["GET"], 1)
        self.assertGreaterEqual(payload["methods"]["POST"], 1)
        self.assertGreaterEqual(payload["references"]["internal_refs"], 1)
        self.assertGreaterEqual(payload["references"]["local_file_refs"], 1)
        self.assertGreaterEqual(payload["references"]["remote_refs_not_fetched"], 1)
        self.assertGreaterEqual(
            payload["references"]["external_docs_not_fetched"],
            1,
        )
        self.assertGreaterEqual(payload["references"]["refs_not_fetched"], 1)
        self.assertGreaterEqual(payload["redactions"]["credentialed_urls"], 1)
        self.assertGreaterEqual(payload["redactions"]["text_summaries"], 1)
        self.assertGreaterEqual(payload["redactions"]["example_summaries"], 1)
        self.assertGreaterEqual(payload["diagnostics"]["parse_errors"], 1)
        self.assertGreaterEqual(payload["diagnostics"]["malformed_specs"], 1)
        self.assertGreaterEqual(payload["generic_config"]["config_documents"], 4)
        self.assertGreaterEqual(payload["generic_config"]["config_paths"], 1)
        self.assertGreaterEqual(payload["generic_config"]["config_references"], 1)
        self.assertGreaterEqual(payload["generic_config"]["config_parse_errors"], 1)
        self.assertTrue(payload["safety"]["no_fetch"])
        self.assertTrue(payload["safety"]["no_api_calls"])
        self.assertTrue(payload["safety"]["no_tool_execution"])
        self.assertTrue(payload["safety"]["raw_profile_only"])
        self.assertTrue(payload["safety"]["no_new_canonical_namespaces"])
        self.assertIn("openapi_documents", table_stdout)
        self.assertIn("openapi3=2", table_stdout)
        self.assertIn("remote_refs_not_fetched", table_stdout)
        self.assertIn("no_fetch=true", table_stdout)

        readback_payload = "\n".join((summary_stdout, table_stdout))
        self.assertNotIn("fake-openapi-json-password", readback_payload)
        self.assertNotIn("fake-openapi-json-token", readback_payload)
        self.assertNotIn("fake-openapi-json-server-secret", readback_payload)
        self.assertNotIn("fake-openapi-yaml-secret", readback_payload)
        self.assertNotIn("user:pass@", readback_payload)
        self.assertGreaterEqual(len(config_documents), 4)
        self.assertFalse(
            any(record.kind.startswith("openapi.") for record in canonical_nodes)
        )
        self.assertEqual(
            {edge.edge_kind for edge in canonical_edges} - {"defines", "references"},
            set(),
        )
