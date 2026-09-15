import json
import unittest

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.graph.keys import css_document_key, html_document_key, js_file_key, js_module_key
from repomap_kg.ops.ingestion.source import (
    SourcePolicyError,
    import_archive_source,
)
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    query_canonical_edge_explanation,
    query_canonical_edge_records,
    query_canonical_node_records,
    query_js_summary,
)
from repomap_test_support.storage_integration import (
    archive_source_fixture,
    fixed_source_clock,
    source_ingestion_fixture_root,
)
from repomap_test_support.source_ingestion_integration import (
    publish_acquisition_summary,
)


class StorageSourceArchiveReadbackIntegrationTests(unittest.TestCase):
    def test_sources_import_archive_loads_local_static_artifact_fixture(self):
        require_postgres_binaries()
        config_path = archive_source_fixture("allowed-test-report.toml")
        root_path = source_ingestion_fixture_root()

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            summary = import_archive_source(
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
            feed_documents = query_canonical_node_records(
                postgres.psql_args,
                root_path=str(root_path),
                kind="feed.document",
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
            styles = query_canonical_edge_records(
                postgres.psql_args,
                root_path=str(root_path),
                kind="styles",
                psql_command=postgres.psql_command,
            )
            html_js_reference = next(
                edge for edge in references
                if edge.target_key == "file:archive_artifacts/example-test-report/static/app.js"
            )
            html_js_explanation = query_canonical_edge_explanation(
                postgres.psql_args, root_path=str(root_path),
                source_key=html_js_reference.source_key, kind=html_js_reference.edge_kind,
                target_key=html_js_reference.target_key,
                identity_metadata_hash=html_js_reference.identity_metadata_hash,
                psql_command=postgres.psql_command,
            )
            js_source_map_reference = next(
                edge for edge in references
                if edge.target_key == "file:archive_artifacts/example-test-report/static/app.js.map"
            )
            js_source_map_explanation = query_canonical_edge_explanation(
                postgres.psql_args, root_path=str(root_path),
                source_key=js_source_map_reference.source_key, kind=js_source_map_reference.edge_kind,
                target_key=js_source_map_reference.target_key,
                identity_metadata_hash=js_source_map_reference.identity_metadata_hash,
                psql_command=postgres.psql_command,
            )
            raw_count = postgres.psql_scalar("SELECT count(*) FROM raw_observations;")

        self.assertEqual(summary.source_id, "example-test-report")
        self.assertEqual(summary.included_files, 8)
        self.assertEqual(publication.files, 8)
        self.assertEqual(raw_count, str(summary.observations))
        self.assertTrue(html_documents)
        self.assertTrue(css_documents)
        self.assertTrue(config_documents)
        self.assertTrue(feed_documents)
        self.assertTrue(js_files)
        self.assertGreaterEqual(js_summary.test_report_asset_files, 1)
        self.assertGreaterEqual(js_summary.source_map_references, 1)
        self.assertTrue(
            any(edge.target_key.startswith("external.url:") for edge in references)
        )
        self.assertIsNotNone(html_js_explanation.edge)
        self.assertTrue(html_js_explanation.evidence)
        self.assertIsNotNone(js_source_map_explanation.edge)
        self.assertTrue(js_source_map_explanation.evidence)
        self.assertTrue(styles)
        source_metadata = json.dumps(
            [observation.to_dict() for observation in summary.raw_observations],
            sort_keys=True,
        )
        self.assertIn('"source_id": "example-test-report"', source_metadata)
        self.assertIn('"artifact_manifest_id"', source_metadata)
        self.assertIn('"profile": "test_report_asset"', source_metadata)
        self.assertIn('"not_fetched": true', source_metadata)
        self.assertIn(
            "file:archive_artifacts/example-test-report/static/app.js.map",
            source_metadata,
        )
        explain_payload = json.dumps(
            {
                "html": html_js_explanation.to_dict(),
                "source_map": js_source_map_explanation.to_dict(),
            },
            sort_keys=True,
        )
        self.assertNotIn("fixture-secret", source_metadata)
        self.assertNotIn("fixture-secret", explain_payload)

    def test_sources_import_archive_cli_preserves_nonpublication_summary(self):
        require_postgres_binaries()
        config_path = archive_source_fixture("allowed-test-report.toml")
        root_path = source_ingestion_fixture_root()

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            exit_code, stdout, stderr = run_repo_map_in_process(
                "sources",
                "import-archive",
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
        self.assertEqual(payload["source_id"], "example-test-report")
        self.assertEqual(payload["source_type"], "test_report.artifact")
        self.assertEqual(payload["included_files"], 8)
        self.assertGreater(payload["observations"], 0)
        self.assertEqual(payload["publication"]["publication_state"], "not_published")
        self.assertEqual(raw_count, "0")

    def test_sources_import_archive_saved_page_readback_replay_and_refusal(self):
        require_postgres_binaries()
        config_path = archive_source_fixture("allowed-saved-page.toml")
        root_path = source_ingestion_fixture_root()

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command,
            )
            summary = import_archive_source(config_path, root_path=root_path, clock=fixed_source_clock)
            publication = publish_acquisition_summary(
                postgres, summary, repository_name="fixture", root_path=root_path,
            )
            html_documents = query_canonical_node_records(
                postgres.psql_args, root_path=str(root_path), kind="html.document", psql_command=postgres.psql_command,
            )
            css_documents = query_canonical_node_records(
                postgres.psql_args, root_path=str(root_path), kind="css.document", psql_command=postgres.psql_command,
            )
            js_files = query_canonical_node_records(
                postgres.psql_args, root_path=str(root_path), kind="js.file", psql_command=postgres.psql_command,
            )
            js_summary = query_js_summary(
                postgres.psql_args, root_path=str(root_path), psql_command=postgres.psql_command,
            )
            references = query_canonical_edge_records(
                postgres.psql_args, root_path=str(root_path), kind="references", psql_command=postgres.psql_command,
            )
            styles = query_canonical_edge_records(
                postgres.psql_args, root_path=str(root_path), kind="styles", psql_command=postgres.psql_command,
            )
            html_js_reference = next(
                edge for edge in references
                if edge.target_key == "file:archive_artifacts/example-saved-page-archive/page_files/app.js"
            )
            html_js_explanation = query_canonical_edge_explanation(
                postgres.psql_args, root_path=str(root_path),
                source_key=html_js_reference.source_key, kind=html_js_reference.edge_kind,
                target_key=html_js_reference.target_key,
                identity_metadata_hash=html_js_reference.identity_metadata_hash,
                psql_command=postgres.psql_command,
            )
            js_source_map_reference = next(
                edge for edge in references
                if edge.target_key == "file:archive_artifacts/example-saved-page-archive/page_files/app.js.map"
            )
            js_source_map_explanation = query_canonical_edge_explanation(
                postgres.psql_args, root_path=str(root_path),
                source_key=js_source_map_reference.source_key, kind=js_source_map_reference.edge_kind,
                target_key=js_source_map_reference.target_key,
                identity_metadata_hash=js_source_map_reference.identity_metadata_hash,
                psql_command=postgres.psql_command,
            )
            js_chunk_reference = next(
                edge for edge in references
                if edge.target_key == "file:archive_artifacts/example-saved-page-archive/page_files/chunk.js"
            )
            js_chunk_explanation = query_canonical_edge_explanation(
                postgres.psql_args, root_path=str(root_path),
                source_key=js_chunk_reference.source_key, kind=js_chunk_reference.edge_kind,
                target_key=js_chunk_reference.target_key,
                identity_metadata_hash=js_chunk_reference.identity_metadata_hash,
                psql_command=postgres.psql_command,
            )
            html_style_reference = next(
                edge for edge in styles
                if edge.target_key == (
                    "html.anchor:file%3Aarchive_artifacts%2Fexample-saved-page-archive%2Fpage.html:saved"
                )
            )
            html_style_explanation = query_canonical_edge_explanation(
                postgres.psql_args, root_path=str(root_path),
                source_key=html_style_reference.source_key, kind=html_style_reference.edge_kind,
                target_key=html_style_reference.target_key,
                identity_metadata_hash=html_style_reference.identity_metadata_hash,
                psql_command=postgres.psql_command,
            )
            raw_count = postgres.psql_scalar("SELECT count(*) FROM raw_observations;")
            files_1 = postgres.psql_scalar(f"SELECT count(*) FROM files WHERE repository_id = {publication.repository_id};")
            nodes_1 = postgres.psql_scalar(f"SELECT count(*) FROM canonical_nodes WHERE repository_id = {publication.repository_id};")
            edges_1 = postgres.psql_scalar(f"SELECT count(*) FROM canonical_edges WHERE repository_id = {publication.repository_id};")

            summary_replay = import_archive_source(config_path, root_path=root_path, clock=fixed_source_clock)
            publication_replay = publish_acquisition_summary(
                postgres, summary_replay, repository_name="fixture", root_path=root_path,
            )
            raw_count_replay = postgres.psql_scalar("SELECT count(*) FROM raw_observations;")
            raw_count_latest = postgres.psql_scalar(
                f"SELECT count(*) FROM raw_observations WHERE run_id = {publication_replay.run_id};"
            )
            files_2 = postgres.psql_scalar(f"SELECT count(*) FROM files WHERE repository_id = {publication_replay.repository_id};")
            nodes_2 = postgres.psql_scalar(f"SELECT count(*) FROM canonical_nodes WHERE repository_id = {publication_replay.repository_id};")
            edges_2 = postgres.psql_scalar(f"SELECT count(*) FROM canonical_edges WHERE repository_id = {publication_replay.repository_id};")

            blocked_config = archive_source_fixture("blocked-policy.toml")
            with self.assertRaises(SourcePolicyError) as blocked_ctx:
                import_archive_source(blocked_config, root_path=root_path, clock=fixed_source_clock)
            self.assertIn("source policy status blocks ingestion: blocked_terms_risk", str(blocked_ctx.exception))
            exit_code, stdout, stderr = run_repo_map_in_process(
                "sources", "import-archive", "--config", str(blocked_config),
                "--root-path", str(root_path), "--json",
            )
            self.assertEqual(exit_code, 1)
            self.assertEqual(stdout, "")
            self.assertIn("source policy status blocks ingestion: blocked_terms_risk", stderr)
            raw_count_after_refusal = postgres.psql_scalar("SELECT count(*) FROM raw_observations;")

        self.assertEqual(summary.source_id, "example-saved-page-archive")
        self.assertEqual(summary.source_type, "saved_page.archive")
        self.assertEqual(summary.policy_status, "allowed_with_limits")
        self.assertEqual(summary.included_files, 6)
        self.assertEqual(summary.manifest.entry_document, "page.html")
        self.assertEqual(summary.manifest.artifact_profile, "saved-page-bundle")
        self.assertEqual(publication.files, 6)
        self.assertEqual(raw_count, str(summary.observations))
        self.assertEqual(len(html_documents), 1)
        self.assertEqual(
            html_documents[0].canonical_key,
            html_document_key("archive_artifacts/example-saved-page-archive/page.html"),
        )
        self.assertEqual(len(css_documents), 1)
        self.assertEqual(
            css_documents[0].canonical_key,
            css_document_key("archive_artifacts/example-saved-page-archive/page_files/style.css"),
        )
        self.assertEqual(len(js_files), 2)
        js_keys = {node.canonical_key for node in js_files}
        self.assertEqual(
            js_keys,
            {
                js_file_key("archive_artifacts/example-saved-page-archive/page_files/app.js"),
                js_file_key("archive_artifacts/example-saved-page-archive/page_files/chunk.js"),
            },
        )
        self.assertEqual(js_summary.saved_page_asset_files, 2)
        self.assertEqual(js_summary.source_map_references, 1)
        self.assertTrue(all(node.metadata.get("profile") == "saved_page_asset" for node in js_files))
        self.assertTrue(any(edge.target_key.startswith("external.url:") for edge in references))
        self.assertIsNotNone(html_js_explanation.edge)
        self.assertTrue(html_js_explanation.evidence)
        self.assertIsNotNone(js_source_map_explanation.edge)
        self.assertTrue(js_source_map_explanation.evidence)
        self.assertEqual(
            js_chunk_reference.source_key,
            js_module_key("archive_artifacts/example-saved-page-archive/page_files/app.js"),
        )
        self.assertEqual(js_chunk_reference.edge_kind, "references")
        self.assertIsNotNone(js_chunk_explanation.edge)
        self.assertTrue(js_chunk_explanation.evidence)
        self.assertIsNotNone(html_style_explanation.edge)
        self.assertTrue(html_style_explanation.evidence)
        self.assertEqual(html_style_reference.edge_kind, "styles")
        self.assertEqual(
            html_style_reference.source_key,
            "css.selector:file%3Aarchive_artifacts%2Fexample-saved-page-archive%2Fpage_files%2Fstyle.css:%2Frule%3A1%2Fselector%3A1",
        )
        self.assertEqual(
            html_style_reference.target_key,
            "html.anchor:file%3Aarchive_artifacts%2Fexample-saved-page-archive%2Fpage.html:saved",
        )
        self.assertEqual(summary_replay.artifact_manifest_id, summary.artifact_manifest_id)
        self.assertEqual(summary_replay.artifact_run_id, summary.artifact_run_id)
        self.assertEqual(publication_replay.files, publication.files)
        self.assertEqual(publication_replay.repository_id, publication.repository_id)
        # Under ADR 0005, raw observations form an append-only audit ledger where
        # UNIQUE (run_id, ordinal) is the idempotence key with fresh physical run identity,
        # while accepted graph entities maintain idempotent current state across replays.
        self.assertEqual(raw_count, "39")
        self.assertEqual(raw_count_latest, "39")
        self.assertEqual(raw_count_replay, "78")
        self.assertEqual(raw_count_after_refusal, "78")
        self.assertEqual(files_1, files_2)
        self.assertEqual(nodes_1, nodes_2)
        self.assertEqual(edges_1, edges_2)

        source_metadata = json.dumps([observation.to_dict() for observation in summary.raw_observations], sort_keys=True)
        self.assertIn('"source_id": "example-saved-page-archive"', source_metadata)
        self.assertIn('"artifact_manifest_id"', source_metadata)
        self.assertIn('"artifact_profile": "saved-page-bundle"', source_metadata)
        self.assertIn('"not_fetched": true', source_metadata)
        self.assertIn("file:archive_artifacts/example-saved-page-archive/page_files/app.js.map", source_metadata)
        explain_payload = json.dumps(
            {
                "chunk": js_chunk_explanation.to_dict(),
                "html": html_js_explanation.to_dict(),
                "source_map": js_source_map_explanation.to_dict(),
                "style": html_style_explanation.to_dict(),
            },
            sort_keys=True,
        )
        self.assertNotIn("fixture-secret", source_metadata)
        self.assertNotIn("fixture-secret", explain_payload)
