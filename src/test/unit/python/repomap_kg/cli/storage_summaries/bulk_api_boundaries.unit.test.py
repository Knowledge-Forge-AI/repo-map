import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from repomap_kg.cli import main
from repomap_kg.storage import StorageSchemaError


class CliStorageBulkApiSummaryBoundariesUnitTests(unittest.TestCase):
    def test_storage_bulk_summary_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_bulk_summary",
            side_effect=StorageSchemaError("psql did not return bulk summary"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "bulk-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("psql did not return bulk summary", stderr.getvalue())

    def test_smoke_harden3_bulk_api_summary_json_omits_raw_manifest_values(self):
        from repomap_kg.storage.summary_rows_manifest import (
            api_manifest_summary_payload,
            api_summary_from_storage_payload,
            bulk_manifest_summary_payload,
            bulk_summary_from_storage_payload,
        )

        synthetic_values = (
            "/Users/synthetic-user/private-repo",
            "/private/tmp/synthetic/repo-map/artifact.json",
            "synthetic-user",
            "synthetic-private-host.invalid",
            "synthetic_private_database",
            "postgresql://synthetic-user:synthetic-secret@example.invalid/db",
            "synthetic-secret-token",
            "raw-secret-response-body",
            "synthetic-private-artifact-path",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bulk_run = root / ".repomap" / "bulk-runs" / "bulk-source" / "bulk-run"
            api_run = root / ".repomap" / "api-runs" / "api-source" / "api-run"
            bulk_bad = root / ".repomap" / "bulk-runs" / "bulk-source" / "bad-run"
            api_bad = root / ".repomap" / "api-runs" / "api-source" / "bad-run"
            bulk_run.mkdir(parents=True)
            api_run.mkdir(parents=True)
            bulk_bad.mkdir(parents=True)
            api_bad.mkdir(parents=True)
            (bulk_run / "manifest.json").write_text(
                json.dumps(
                    {
                        "source_id": "bulk-source",
                        "bulk_run_id": "bulk-run",
                        "corpus_kind": "mixed_corpus",
                        "policy_status": "allowed_with_limits",
                        "file_count_included": 2,
                        "file_count_skipped": 1,
                        "total_bytes_included": 256,
                        "diagnostic_counts": {"private_path_redacted": 1},
                        "redaction_counts": {"credential": 2, "private_path": 1},
                        "skipped_files": [
                            {
                                "relative_path": (
                                    "/Users/synthetic-user/private-repo/secret.txt"
                                ),
                                "reason": "hidden_excluded",
                            }
                        ],
                        "artifact_path": (
                            "/private/tmp/synthetic/repo-map/artifact.json"
                        ),
                        "raw_payload": {"body": "raw-secret-response-body"},
                        "connection": (
                            "postgresql://synthetic-user:synthetic-secret@example.invalid/db"
                        ),
                        "token": "synthetic-secret-token",
                        "database": "synthetic_private_database",
                        "host": "synthetic-private-host.invalid",
                    }
                ),
                encoding="utf-8",
            )
            (bulk_bad / "manifest.json").write_text(
                "raw-secret-response-body from /Users/synthetic-user/private-repo",
                encoding="utf-8",
            )
            (api_run / "manifest.json").write_text(
                json.dumps(
                    {
                        "source_id": "api-source",
                        "api_run_id": "api-run",
                        "source_type": "api.rest",
                        "api_source_class": "api.custom_documented_api",
                        "provider_name": "Fixture Provider",
                        "provider_product": "Fixture API",
                        "policy_status": "allowed_with_limits",
                        "requests": [
                            {
                                "endpoint_name": "items",
                                "method": "GET",
                                "downstream_route": "config",
                                "response_type": "application/json",
                                "url": (
                                    "https://synthetic-private-host.invalid/items"
                                    "?token=synthetic-secret-token"
                                ),
                            }
                        ],
                        "responses": [
                            {
                                "endpoint_name": "items",
                                "response_byte_count": 512,
                                "redacted": True,
                                "artifact_path": "synthetic-private-artifact-path",
                                "raw_response_body": "raw-secret-response-body",
                            }
                        ],
                        "connection": (
                            "postgresql://synthetic-user:synthetic-secret@example.invalid/db"
                        ),
                        "database": "synthetic_private_database",
                        "root_path": "/Users/synthetic-user/private-repo",
                        "artifact_path": (
                            "/private/tmp/synthetic/repo-map/artifact.json"
                        ),
                        "no_network": True,
                        "no_mutation": True,
                        "no_credentials_resolved": True,
                        "no_scheduler": True,
                    }
                ),
                encoding="utf-8",
            )
            (api_bad / "manifest.json").write_text(
                "synthetic-secret-token from synthetic-private-host.invalid",
                encoding="utf-8",
            )

            bulk_summary = bulk_summary_from_storage_payload(
                bulk_manifest_summary_payload(root)
            )
            api_summary = api_summary_from_storage_payload(
                api_manifest_summary_payload(root)
            )

        bulk_stdout = io.StringIO()
        api_stdout = io.StringIO()
        with patch("repomap_kg.cli.query_bulk_summary", return_value=bulk_summary):
            with redirect_stdout(bulk_stdout):
                bulk_exit = main(
                    [
                        "storage",
                        "bulk-summary",
                        "--root-path",
                        "/tmp/fixture",
                        "--json",
                    ]
                )
        with patch("repomap_kg.cli.query_api_summary", return_value=api_summary):
            with redirect_stdout(api_stdout):
                api_exit = main(
                    [
                        "storage",
                        "api-summary",
                        "--root-path",
                        "/tmp/fixture",
                        "--json",
                    ]
                )

        bulk_payload = json.loads(bulk_stdout.getvalue())
        api_payload = json.loads(api_stdout.getvalue())
        self.assertEqual(bulk_exit, 0)
        self.assertEqual(api_exit, 0)
        self.assertEqual(
            bulk_payload["redaction_counts"],
            {"credential": 2, "private_path": 1},
        )
        self.assertEqual(bulk_payload["diagnostic_counts"]["manifest_parse_error"], 1)
        self.assertEqual(api_payload["redacted_responses"], 1)
        self.assertEqual(api_payload["routed_artifacts"], 1)
        self.assertEqual(api_payload["diagnostic_counts"]["manifest_parse_error"], 1)
        serialized = json.dumps(
            {"bulk": bulk_payload, "api": api_payload},
            sort_keys=True,
        )
        for synthetic_value in synthetic_values:
            self.assertNotIn(synthetic_value, serialized)

    def test_storage_api_summary_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_api_summary",
            side_effect=StorageSchemaError("psql did not return api summary"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "api-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("psql did not return api summary", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
