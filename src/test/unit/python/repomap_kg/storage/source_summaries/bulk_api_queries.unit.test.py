import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from repomap_kg.storage import (
    StorageSchemaError,
    query_bulk_summary,
)

class StorageSourceBulkApiQueryUnitTests(unittest.TestCase):
    def test_query_bulk_summary_combines_manifests_and_bulk_provenance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            run_dir = root / ".repomap" / "bulk-runs" / "source-one" / "run-one"
            run_dir.mkdir(parents=True)
            (run_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "bulk_run_id": "run-one",
                        "source_id": "source-one",
                        "source_type": "local.directory",
                        "corpus_kind": "mixed_corpus",
                        "policy_status": "allowed_with_limits",
                        "file_count_included": 3,
                        "file_count_skipped": 2,
                        "total_bytes_included": 123,
                        "limit_hit": True,
                        "limit_reason": "max_files_exceeded",
                        "extractor_counts": {"eml": 1, "javascript": 1},
                        "diagnostic_counts": {"extractor_error": 1},
                        "redaction_counts": {"raw_observations": 2},
                        "skipped_files": [
                            {"relative_path": ".hidden/a.eml", "reason": "hidden_excluded"},
                            {"relative_path": "archive/export.zip", "reason": "archive_deferred"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            storage_payload = {
                "repository_name": "fixture",
                "observations_with_bulk_provenance": 7,
                "redacted_observations": 2,
            }
            with patch(
                "repomap_kg.storage.summaries.execute_json_readback", return_value=storage_payload
            ) as readback:
                summary = query_bulk_summary(
                    ["-d", "postgres"],
                    root_path=str(root),
                    psql_command="/bin/psql",
                )

        self.assertEqual(summary.root_path_summary, ".")
        self.assertEqual(summary.repository_name, "fixture")
        self.assertEqual(summary.bulk_runs, 1)
        self.assertEqual(summary.sources, 1)
        self.assertEqual(summary.source_ids, ("source-one",))
        self.assertEqual(summary.corpus_kinds["mixed_corpus"], 1)
        self.assertEqual(summary.policy_statuses["allowed_with_limits"], 1)
        self.assertEqual(summary.file_count_included, 3)
        self.assertEqual(summary.file_count_skipped, 2)
        self.assertEqual(summary.extractor_counts["eml"], 1)
        self.assertEqual(summary.skip_reasons["archive_deferred"], 1)
        self.assertEqual(summary.archive_deferred, 1)
        self.assertEqual(summary.limit_hit_count, 1)
        self.assertEqual(summary.max_files_hit_count, 1)
        self.assertEqual(summary.observations_with_bulk_provenance, 7)
        self.assertEqual(summary.redaction_counts["raw_observations"], 2)
        self.assertTrue(summary.no_provider_api)
        self.assertTrue(summary.no_external_fetch)
        self.assertTrue(summary.no_source_mutation)
        self.assertTrue(summary.no_archive_decompression)
        self.assertIn("payload_json->'metadata' ? 'bulk_run_id'", readback.call_args.args[0])
    def test_query_bulk_summary_handles_rich_limit_reasons_and_bad_manifests(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            good_run = root / ".repomap" / "bulk-runs" / "source-two" / "run-two"
            non_dict_run = root / ".repomap" / "bulk-runs" / "source-three" / "run-three"
            malformed_run = root / ".repomap" / "bulk-runs" / "source-four" / "run-four"
            good_run.mkdir(parents=True)
            non_dict_run.mkdir(parents=True)
            malformed_run.mkdir(parents=True)
            (good_run / "manifest.json").write_text(
                json.dumps(
                    {
                        "bulk_run_id": "run-two",
                        "source_id": "source-two",
                        "corpus_kind": "email_export",
                        "policy_status": "allowed_with_limits",
                        "file_count_included": 5,
                        "file_count_skipped": 4,
                        "total_bytes_included": 2048,
                        "limit_hit": True,
                        "limit_reason": (
                            "max_total_bytes_exceeded, "
                            "max_file_bytes_exceeded, max_depth_exceeded"
                        ),
                        "extractor_counts": {"markdown": 3},
                        "diagnostic_counts": {"too_large": 1},
                        "redaction_counts": {"secrets": 2},
                        "skipped_files": [
                            {"reason": "warc_deferred"},
                            {"reason": None},
                            {},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (non_dict_run / "manifest.json").write_text("[]\n", encoding="utf-8")
            (malformed_run / "manifest.json").write_text("{not-json", encoding="utf-8")
            storage_payload = {
                "repository_name": "fixture",
                "observations_with_bulk_provenance": 2,
                "redacted_observations": 1,
            }
            with patch(
                "repomap_kg.storage.summaries.execute_json_readback", return_value=storage_payload
            ):
                summary = query_bulk_summary(["-d", "postgres"], root_path=str(root))

        self.assertEqual(summary.bulk_runs, 1)
        self.assertEqual(summary.sources, 1)
        self.assertEqual(summary.email_export_runs, 1)
        self.assertEqual(summary.file_count_included, 5)
        self.assertEqual(summary.file_count_skipped, 4)
        self.assertEqual(summary.total_bytes_included, 2048)
        self.assertEqual(summary.extractor_counts["markdown"], 3)
        self.assertEqual(summary.diagnostic_counts["too_large"], 1)
        self.assertEqual(summary.diagnostic_counts["manifest_parse_error"], 2)
        self.assertEqual(summary.redaction_counts["secrets"], 2)
        self.assertEqual(summary.limit_hit_count, 1)
        self.assertEqual(summary.max_total_bytes_hit_count, 1)
        self.assertEqual(summary.max_file_bytes_hit_count, 1)
        self.assertEqual(summary.max_depth_hit_count, 1)
        self.assertEqual(summary.warc_deferred, 1)
    def test_query_bulk_summary_empty_repo_returns_zero_counts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_payload = {
                "repository_name": None,
                "observations_with_bulk_provenance": 0,
                "redacted_observations": 0,
            }

            with patch(
                "repomap_kg.storage.summaries.execute_json_readback", return_value=storage_payload
            ):
                summary = query_bulk_summary(["-d", "postgres"], root_path=tmpdir)

        self.assertEqual(summary.bulk_runs, 0)
        self.assertEqual(summary.sources, 0)
        self.assertEqual(summary.file_count_included, 0)
        self.assertEqual(summary.file_count_skipped, 0)
        self.assertEqual(summary.extractor_counts, {})
        self.assertEqual(summary.skip_reasons, {})
        self.assertEqual(summary.observations_with_bulk_provenance, 0)
        self.assertTrue(summary.no_provider_api)
    def test_query_bulk_summary_rejects_escaped_manifest_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with tempfile.TemporaryDirectory() as escaped_tmpdir:
                root = Path(tmpdir)
                escaped_root = Path(escaped_tmpdir) / "bulk-runs"
                escaped_root.mkdir()
                (root / ".repomap").mkdir()
                (root / ".repomap" / "bulk-runs").symlink_to(
                    escaped_root,
                    target_is_directory=True,
                )
                storage_payload = {
                    "repository_name": None,
                    "observations_with_bulk_provenance": 0,
                    "redacted_observations": 0,
                }

                with patch(
                    "repomap_kg.storage.summaries.execute_json_readback", return_value=storage_payload
                ):
                    summary = query_bulk_summary(["-d", "postgres"], root_path=tmpdir)

        self.assertEqual(summary.bulk_runs, 0)
        self.assertEqual(summary.sources, 0)
        self.assertEqual(summary.diagnostic_counts["manifest_parse_error"], 1)
        self.assertTrue(summary.no_provider_api)
    def test_query_bulk_summary_rejects_malformed_storage_json(self):
        storage_payload = {"repository_name": "fixture"}

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "repomap_kg.storage.summaries.execute_json_readback", return_value=storage_payload
            ):
                with self.assertRaisesRegex(StorageSchemaError, "bulk summary"):
                    query_bulk_summary(["-d", "postgres"], root_path=tmpdir)
