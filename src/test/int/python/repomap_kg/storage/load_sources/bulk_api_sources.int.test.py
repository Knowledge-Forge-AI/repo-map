import json
import shutil
import tempfile
import unittest
from pathlib import Path

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.ops.ingestion.api import acquire_api_source
from repomap_kg.ops.ingestion.bulk import import_bulk_source
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    query_api_summary,
    query_bulk_summary,
    query_canonical_node_records,
)

from repomap_test_support.storage_integration import (
    api_fixture_root,
    bulk_fixture_root,
    publish_acquisition_summary,
)


class StorageBulkApiSourceLoadIntegrationTests(unittest.TestCase):
    def test_bulk_import_cli_requires_explicit_staged_publication(self):
        require_postgres_binaries()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shutil.copytree(
                bulk_fixture_root() / "mixed_corpus",
                root / "mixed_corpus",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            corpus = root / "mixed_corpus"
            corpus_root = str(corpus.resolve())
            input_body = (corpus / "mail" / "single-message.eml").read_text(
                encoding="utf-8"
            )
            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                exit_code, stdout, stderr = run_repo_map_in_process(
                    "bulk",
                    "import",
                    "--config",
                    str(corpus / "bulk.toml"),
                    "--root-path",
                    corpus_root,
                    "--json",
                )
                unpublished_raw_count = postgres.psql_scalar(
                    "SELECT count(*)::text FROM raw_observations;"
                )
                unpublished_kinds = {
                    record.kind
                    for record in query_canonical_node_records(
                        postgres.psql_args,
                        root_path=corpus_root,
                        psql_command=postgres.psql_command,
                    )
                }
                shutil.rmtree(corpus / ".repomap")
                summary = import_bulk_source(
                    corpus / "bulk.toml",
                    root_path=corpus,
                )
                publish_acquisition_summary(
                    postgres,
                    summary,
                    repository_name="fixture-bulk",
                    root_path=corpus,
                )
                kinds = {
                    record.kind
                    for record in query_canonical_node_records(
                        postgres.psql_args,
                        root_path=corpus_root,
                        psql_command=postgres.psql_command,
                    )
                }
                raw_payload = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                )
                bulk_summary = query_bulk_summary(
                    postgres.psql_args,
                    root_path=corpus_root,
                    psql_command=postgres.psql_command,
                )
                bulk_summary_exit_code, bulk_summary_stdout, bulk_summary_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "bulk-summary",
                        "--root-path",
                        corpus_root,
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
                    "bulk-summary",
                    "--root-path",
                    corpus_root,
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
                manifest_count = postgres.psql_scalar(
                    """
SELECT count(*)::text
FROM raw_observations
WHERE payload_json->'metadata' ? 'bulk_run_id';
"""
                )
                manifest_dir_exists = (corpus / ".repomap" / "bulk-runs").is_dir()

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["source_id"], "fixture-mixed-corpus")
        self.assertTrue(payload["no_provider_api"])
        self.assertEqual(payload["publication"]["publication_state"], "not_published")
        self.assertEqual(unpublished_raw_count, "0")
        self.assertEqual(unpublished_kinds, set())
        self.assertTrue(manifest_dir_exists)
        self.assertEqual(
            kinds,
            {
                "config.document",
                "config.path",
                "doc.page",
                "doc.section",
                "email.address",
                "email.message",
                "email.part",
                "external",
                "external.url",
                "file",
                "html.document",
                "html.element",
                "js.file",
                "js.function",
                "js.module",
                "python.function",
                "python.module",
            },
        )
        self.assertNotEqual(manifest_count, "0")
        self.assertIn("bulk_relative_path", raw_payload)
        self.assertNotIn(str(corpus), raw_payload)
        self.assertNotIn("mixed-corpus-secret-value", raw_payload)
        self.assertIn("mixed-corpus-secret-value", input_body)
        self.assertEqual(bulk_summary_exit_code, 0, bulk_summary_stderr)
        self.assertEqual(table_exit_code, 0, table_stderr)
        bulk_summary_payload = json.loads(bulk_summary_stdout)
        self.assertEqual(bulk_summary.bulk_runs, 1)
        self.assertEqual(bulk_summary.sources, 1)
        self.assertEqual(bulk_summary.source_ids, ("fixture-mixed-corpus",))
        self.assertEqual(bulk_summary.corpus_kinds["mixed_corpus"], 1)
        self.assertEqual(bulk_summary.file_count_included, 6)
        self.assertEqual(bulk_summary.file_count_skipped, 2)
        self.assertEqual(bulk_summary.extractor_counts["javascript"], 1)
        self.assertEqual(bulk_summary.skip_reasons["excluded_directory"], 1)
        self.assertEqual(bulk_summary.observations_with_bulk_provenance, 44)
        self.assertTrue(bulk_summary.no_provider_api)
        self.assertTrue(bulk_summary.no_external_fetch)
        self.assertTrue(bulk_summary.no_source_mutation)
        self.assertTrue(bulk_summary.no_archive_decompression)
        self.assertEqual(bulk_summary_payload["bulk_runs"], 1)
        self.assertEqual(bulk_summary_payload["source_ids"], ["fixture-mixed-corpus"])
        self.assertEqual(bulk_summary_payload["corpus_kinds"]["mixed_corpus"], 1)
        self.assertNotIn(str(corpus), bulk_summary_stdout)
        self.assertNotIn("mixed-corpus-secret-value", bulk_summary_stdout)
        self.assertIn("bulk_runs", table_stdout)
        self.assertIn("mixed_corpus=1", table_stdout)
        self.assertNotIn(str(corpus), table_stdout)
        self.assertNotIn("mixed-corpus-secret-value", table_stdout)

    def test_api_acquire_cli_requires_explicit_staged_publication(self):
        require_postgres_binaries()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shutil.copytree(
                api_fixture_root() / "readonly_fixture_api",
                root / "readonly_fixture_api",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            config_path = root / "readonly_fixture_api" / "api-source.toml"
            source_text = (
                root / "readonly_fixture_api" / "responses" / "items.json"
            ).read_text(encoding="utf-8")
            root_path = str(root.resolve())
            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                exit_code, stdout, stderr = run_repo_map_in_process(
                    "api",
                    "acquire",
                    "--config",
                    str(config_path),
                    "--root-path",
                    root_path,
                    "--json",
                )
                unpublished_raw_count = postgres.psql_scalar(
                    "SELECT count(*)::text FROM raw_observations;"
                )
                unpublished_kinds = {
                    record.kind
                    for record in query_canonical_node_records(
                        postgres.psql_args,
                        root_path=root_path,
                        psql_command=postgres.psql_command,
                    )
                }
                summary = acquire_api_source(
                    config_path,
                    root_path=root,
                )
                publish_acquisition_summary(
                    postgres,
                    summary,
                    repository_name="fixture-api",
                    root_path=root,
                )
                kinds = {
                    record.kind
                    for record in query_canonical_node_records(
                        postgres.psql_args,
                        root_path=root_path,
                        psql_command=postgres.psql_command,
                    )
                }
                raw_payload = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                )
                api_canonical_count = postgres.psql_scalar(
                    """
SELECT count(*)::text
FROM canonical_nodes
WHERE kind LIKE 'api.%';
"""
                )
                provenance_count = postgres.psql_scalar(
                    """
SELECT count(*)::text
FROM raw_observations
WHERE payload_json->'metadata' ? 'api_run_id';
"""
                )
                api_summary = query_api_summary(
                    postgres.psql_args,
                    root_path=root_path,
                    psql_command=postgres.psql_command,
                )
                api_summary_exit_code, api_summary_stdout, api_summary_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "api-summary",
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
                    "api-summary",
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
                manifest_dir_exists = (root / ".repomap" / "api-runs").is_dir()

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        api_summary_payload = json.loads(api_summary_stdout)
        self.assertEqual(payload["source_id"], "fixture-readonly-api")
        self.assertTrue(payload["no_network"])
        self.assertTrue(payload["no_mutation"])
        self.assertEqual(payload["publication"]["publication_state"], "not_published")
        self.assertEqual(unpublished_raw_count, "0")
        self.assertEqual(unpublished_kinds, set())
        self.assertTrue(manifest_dir_exists)
        self.assertEqual(kinds, {"config.document", "config.path", "file"})
        self.assertEqual(api_canonical_count, "0")
        self.assertNotEqual(provenance_count, "0")
        self.assertIn("api.response", raw_payload)
        self.assertIn("api_retention_policy", raw_payload)
        self.assertIn("config.document", raw_payload)
        self.assertNotIn(str(root), raw_payload)
        self.assertNotIn("fixture-secret-value", raw_payload)
        self.assertNotIn("fixture-api-token", raw_payload)
        self.assertIn("fixture-secret-value", source_text)
        self.assertNotIn(str(root), stdout)
        self.assertNotIn("fixture-secret-value", stdout)
        self.assertEqual(api_summary_exit_code, 0, api_summary_stderr)
        self.assertEqual(table_exit_code, 0, table_stderr)
        self.assertEqual(api_summary.api_runs, 1)
        self.assertEqual(api_summary.sources, 1)
        self.assertEqual(api_summary.source_ids, ("fixture-readonly-api",))
        self.assertEqual(api_summary.source_types["api.rest"], 1)
        self.assertEqual(
            api_summary.api_source_classes["api.custom_documented_api"],
            1,
        )
        self.assertEqual(api_summary.provider_names["Fixture Provider"], 1)
        self.assertEqual(api_summary.policy_statuses["allowed_with_limits"], 1)
        self.assertEqual(api_summary.requests, 1)
        self.assertEqual(api_summary.responses, 1)
        self.assertEqual(api_summary.methods["GET"], 1)
        self.assertEqual(api_summary.downstream_routes["config"], 1)
        self.assertEqual(api_summary.response_types["application/json"], 1)
        self.assertEqual(api_summary.redacted_responses, 1)
        self.assertEqual(api_summary.routed_artifacts, 1)
        self.assertEqual(api_summary.observations_with_api_provenance, 6)
        self.assertEqual(api_summary.config_documents_from_api, 1)
        self.assertTrue(api_summary.no_network)
        self.assertTrue(api_summary.no_mutation)
        self.assertTrue(api_summary.no_credentials_resolved)
        self.assertTrue(api_summary.no_scheduler)
        self.assertTrue(api_summary.no_provider_specific_behavior)
        self.assertEqual(api_summary_payload["api_runs"], 1)
        self.assertEqual(api_summary_payload["source_ids"], ["fixture-readonly-api"])
        self.assertEqual(api_summary_payload["methods"]["GET"], 1)
        self.assertNotIn(str(root), api_summary_stdout)
        self.assertNotIn("fixture-secret-value", api_summary_stdout)
        self.assertNotIn("fixture-api-token", api_summary_stdout)
        self.assertNotIn(str(root), table_stdout)
        self.assertNotIn("fixture-secret-value", table_stdout)
        self.assertNotIn("fixture-api-token", table_stdout)
        self.assertIn("api_runs", table_stdout)
        self.assertIn("Fixture Provider=1", table_stdout)
