import json
import tempfile
import unittest
from pathlib import Path

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.ops.ingestion.source import import_warc_source
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    query_canonical_edge_explanation,
    query_canonical_edge_records,
    query_canonical_node_records,
    query_js_summary,
)
from repomap_test_support.storage_integration import (
    copy_warc_fixture_root,
    fixed_source_clock,
)
from repomap_test_support.source_ingestion_integration import (
    publish_acquisition_summary,
)


class StorageSourceWarcReadbackIntegrationTests(unittest.TestCase):
    def test_sources_import_warc_loads_local_warc_fixture(self):
        require_postgres_binaries()

        with tempfile.TemporaryDirectory() as tmpdir:
            root_path = copy_warc_fixture_root(Path(tmpdir))
            config_path = root_path / "warc_sources" / "allowed-warc.toml"
            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                summary = import_warc_source(
                    config_path,
                    root_path=root_path,
                    clock=fixed_source_clock,
                )
                publication = publish_acquisition_summary(
                    postgres,
                    summary,
                    repository_name="fixture",
                    root_path=root_path,
                )
                warc_documents = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(root_path),
                    kind="warc.document",
                    psql_command=postgres.psql_command,
                )
                warc_records = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(root_path),
                    kind="warc.record",
                    psql_command=postgres.psql_command,
                )
                html_documents = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(root_path),
                    kind="html.document",
                    psql_command=postgres.psql_command,
                )
                css_documents = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(root_path),
                    kind="css.document",
                    psql_command=postgres.psql_command,
                )
                config_documents = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(root_path),
                    kind="config.document",
                    psql_command=postgres.psql_command,
                )
                js_files = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(root_path),
                    kind="js.file",
                    psql_command=postgres.psql_command,
                )
                js_summary = query_js_summary(
                    postgres.psql_args,
                    root_path=str(root_path),
                    psql_command=postgres.psql_command,
                )
                references = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=str(root_path),
                    kind="references",
                    psql_command=postgres.psql_command,
                )
                raw_count = postgres.psql_scalar("SELECT count(*) FROM raw_observations;")
                warc_reference = next(
                    edge
                    for edge in references
                    if edge.source_key.startswith("warc.record:")
                    and edge.target_key.startswith("external.url:")
                )
                explanation = query_canonical_edge_explanation(
                    postgres.psql_args,
                    root_path=str(root_path),
                    source_key=warc_reference.source_key,
                    kind=warc_reference.edge_kind,
                    target_key=warc_reference.target_key,
                    identity_metadata_hash=warc_reference.identity_metadata_hash,
                    psql_command=postgres.psql_command,
                )
                js_source_map_reference = next(
                    edge
                    for edge in references
                    if edge.target_key.endswith("/record-0005/payload.js.map")
                )
                js_source_map_explanation = query_canonical_edge_explanation(
                    postgres.psql_args,
                    root_path=str(root_path),
                    source_key=js_source_map_reference.source_key,
                    kind=js_source_map_reference.edge_kind,
                    target_key=js_source_map_reference.target_key,
                    identity_metadata_hash=js_source_map_reference.identity_metadata_hash,
                    psql_command=postgres.psql_command,
                )

        self.assertEqual(summary.source_id, "example-warc-archive")
        self.assertEqual(summary.record_count, 8)
        self.assertEqual(summary.routed_payloads, 4)
        self.assertEqual(publication.files, 4)
        self.assertEqual(raw_count, str(summary.observations))
        self.assertEqual(len(warc_documents), 1)
        self.assertEqual(len(warc_records), 8)
        self.assertTrue(html_documents)
        self.assertTrue(css_documents)
        self.assertTrue(config_documents)
        self.assertTrue(js_files)
        self.assertGreaterEqual(js_summary.saved_page_asset_files, 1)
        self.assertGreaterEqual(js_summary.source_map_references, 1)
        self.assertTrue(
            any(edge.source_key.startswith("warc.record:") for edge in references)
        )
        self.assertIsNotNone(explanation.edge)
        self.assertTrue(explanation.evidence)
        self.assertIsNotNone(js_source_map_explanation.edge)
        self.assertTrue(js_source_map_explanation.evidence)
        source_metadata = json.dumps(
            [observation.to_dict() for observation in summary.raw_observations],
            sort_keys=True,
        )
        explain_payload = json.dumps(
            {
                "warc": explanation.to_dict(),
                "source_map": js_source_map_explanation.to_dict(),
            },
            sort_keys=True,
        )
        self.assertIn('"warc_record_key"', source_metadata)
        self.assertIn('"warc_payload_path"', source_metadata)
        self.assertIn('"artifact_extractor_route": "javascript"', source_metadata)
        self.assertIn('"not_fetched": true', source_metadata)
        self.assertNotIn("fixture-secret", source_metadata)
        self.assertNotIn("fixture-secret", explain_payload)

    def test_sources_import_warc_cli_preserves_nonpublication_summary(self):
        require_postgres_binaries()

        with tempfile.TemporaryDirectory() as tmpdir:
            root_path = copy_warc_fixture_root(Path(tmpdir))
            config_path = root_path / "warc_sources" / "allowed-warc.toml"
            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                exit_code, stdout, stderr = run_repo_map_in_process(
                    "sources",
                    "import-warc",
                    "--config",
                    str(config_path),
                    "--root-path",
                    str(root_path),
                    "--json",
                )
                raw_count = postgres.psql_scalar("SELECT count(*) FROM raw_observations;")

        self.assertEqual(exit_code, 0, stderr)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["source_id"], "example-warc-archive")
        self.assertEqual(payload["source_type"], "saved_page.archive")
        self.assertEqual(payload["record_count"], 8)
        self.assertEqual(payload["routed_payloads"], 4)
        self.assertGreater(payload["observations"], 0)
        self.assertEqual(payload["publication"]["publication_state"], "not_published")
        self.assertEqual(raw_count, "0")
