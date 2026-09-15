import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.public_branch_contracts import (
    warc_record,
    write_warc_config,
)
from repomap_kg.ops.ingestion.source import build_warc_manifest, load_warc_source_config
from repomap_kg.storage import query_api_summary, query_bulk_summary


class PublicBranchSourceStorageWarcIntegrationTests(unittest.TestCase):
    def test_storage_summaries_handle_limit_reasons_and_malformed_manifests(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            good_bulk = root / ".repomap" / "bulk-runs" / "source-two" / "run-two"
            bad_bulk = root / ".repomap" / "bulk-runs" / "source-three" / "run-three"
            malformed_bulk = root / ".repomap" / "bulk-runs" / "source-four" / "run-four"
            good_api = root / ".repomap" / "api-runs" / "source-two" / "run-two"
            bad_api = root / ".repomap" / "api-runs" / "source-three" / "run-three"
            malformed_api = root / ".repomap" / "api-runs" / "source-four" / "run-four"
            for run_dir in (
                good_bulk,
                bad_bulk,
                malformed_bulk,
                good_api,
                bad_api,
                malformed_api,
            ):
                run_dir.mkdir(parents=True)
            (good_bulk / "manifest.json").write_text(
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
            (bad_bulk / "manifest.json").write_text("[]\n", encoding="utf-8")
            (malformed_bulk / "manifest.json").write_text("{not-json", encoding="utf-8")
            (good_api / "manifest.json").write_text(
                json.dumps(
                    {
                        "api_run_id": "run-two",
                        "source_id": "source-two",
                        "source_type": "api.rest",
                        "api_source_class": "api.custom_documented_api",
                        "provider_name": "Fixture Provider",
                        "provider_product": "Fixture API",
                        "policy_status": "allowed_with_limits",
                        "requests": [
                            {
                                "endpoint_name": "items",
                                "method": "GET",
                                "downstream_route": "graph",
                                "response_type": "application/json",
                            },
                            {
                                "endpoint_name": None,
                                "method": None,
                                "downstream_route": None,
                                "response_type": None,
                            },
                        ],
                        "responses": [
                            {
                                "endpoint_name": "items",
                                "response_byte_count": 128,
                                "redacted": False,
                                "artifact_path": None,
                            },
                            {
                                "endpoint_name": None,
                                "response_byte_count": 256,
                                "redacted": True,
                                "artifact_path": "artifacts/item.json",
                            },
                        ],
                        "no_network": False,
                        "no_mutation": False,
                        "no_credentials_resolved": False,
                        "no_scheduler": False,
                    }
                ),
                encoding="utf-8",
            )
            (bad_api / "manifest.json").write_text("[]\n", encoding="utf-8")
            (malformed_api / "manifest.json").write_text("{not-json", encoding="utf-8")
            bulk_payload = {
                "repository_name": "fixture",
                "observations_with_bulk_provenance": 2,
                "redacted_observations": 1,
            }
            api_payload = {
                "repository_name": "fixture",
                "observations_with_api_provenance": 4,
                "config_documents_from_api": 2,
            }

            with (
                patch(
                    "repomap_kg.storage.summaries.execute_json_readback",
                    side_effect=(bulk_payload, api_payload),
                ),
            ):
                bulk_summary = query_bulk_summary(["-d", "postgres"], root_path=str(root))
                api_summary = query_api_summary(["-d", "postgres"], root_path=str(root))

        self.assertEqual(bulk_summary.bulk_runs, 1)
        self.assertEqual(bulk_summary.email_export_runs, 1)
        self.assertEqual(bulk_summary.file_count_included, 5)
        self.assertEqual(bulk_summary.file_count_skipped, 4)
        self.assertEqual(bulk_summary.total_bytes_included, 2048)
        self.assertEqual(bulk_summary.extractor_counts["markdown"], 3)
        self.assertEqual(bulk_summary.diagnostic_counts["too_large"], 1)
        self.assertEqual(bulk_summary.diagnostic_counts["manifest_parse_error"], 2)
        self.assertEqual(bulk_summary.redaction_counts["secrets"], 2)
        self.assertEqual(bulk_summary.limit_hit_count, 1)
        self.assertEqual(bulk_summary.max_total_bytes_hit_count, 1)
        self.assertEqual(bulk_summary.max_file_bytes_hit_count, 1)
        self.assertEqual(bulk_summary.max_depth_hit_count, 1)
        self.assertEqual(bulk_summary.warc_deferred, 1)
        self.assertEqual(api_summary.api_runs, 1)
        self.assertEqual(api_summary.requests, 2)
        self.assertEqual(api_summary.responses, 2)
        self.assertEqual(api_summary.endpoints, 1)
        self.assertEqual(api_summary.endpoint_names, ("items",))
        self.assertEqual(api_summary.methods["GET"], 1)
        self.assertEqual(api_summary.downstream_routes["graph"], 1)
        self.assertEqual(api_summary.response_types["application/json"], 1)
        self.assertEqual(api_summary.response_byte_count, 384)
        self.assertEqual(api_summary.redacted_responses, 1)
        self.assertEqual(api_summary.routed_artifacts, 1)
        self.assertEqual(api_summary.diagnostic_counts["manifest_parse_error"], 2)
        self.assertFalse(api_summary.no_network)
        self.assertFalse(api_summary.no_mutation)
        self.assertFalse(api_summary.no_credentials_resolved)
        self.assertFalse(api_summary.no_scheduler)

    def test_warc_manifest_skip_and_error_contracts_are_preserved(self):
        fixed_clock = lambda: datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC)
        cases = {
            "missing_header_terminator": (
                b"not a warc",
                "missing header terminator",
            ),
            "unsupported_version": (
                b"WARC/0.9\r\nContent-Length: 0\r\n\r\n",
                "unsupported WARC version",
            ),
            "missing_content_length": (
                b"WARC/1.1\r\nWARC-Type: response\r\n\r\n",
                "missing Content-Length",
            ),
            "invalid_content_length": (
                b"WARC/1.1\r\nContent-Length: nope\r\n\r\n",
                "invalid Content-Length",
            ),
            "negative_content_length": (
                b"WARC/1.1\r\nContent-Length: -1\r\n\r\n",
                "negative Content-Length",
            ),
            "truncated_payload": (
                b"WARC/1.1\r\nContent-Length: 10\r\n\r\nx",
                "truncated payload",
            ),
        }

        for name, (content, expected_error) in cases.items():
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = Path(tmpdir) / "repo"
                    artifact_dir = root / "warc_artifacts"
                    artifact_dir.mkdir(parents=True)
                    (artifact_dir / "example.warc").write_bytes(content)
                    config = load_warc_source_config(write_warc_config(root / "warc.toml"))

                    manifest = build_warc_manifest(config, root_path=root, clock=fixed_clock)

                self.assertTrue(
                    any(expected_error in error for error in manifest.errors),
                    manifest.errors,
                )
                self.assertEqual(manifest.routed_payload_count, 0)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            artifact_dir = root / "warc_artifacts"
            artifact_dir.mkdir(parents=True)
            (artifact_dir / "example.warc").write_bytes(
                b"".join(
                    [
                        warc_record(
                            "resource",
                            "urn:uuid:empty-html",
                            "https://example.invalid/empty.html",
                            b"",
                            content_type="text/html",
                        ),
                        warc_record(
                            "continuation",
                            "urn:uuid:continuation",
                            "https://example.invalid/continuation",
                            b"continued bytes",
                            content_type="text/html",
                        ),
                        warc_record(
                            "weird-record",
                            "urn:uuid:weird",
                            "https://example.invalid/weird",
                            b"weird bytes",
                            content_type="text/html",
                        ),
                        warc_record(
                            "resource",
                            "urn:uuid:unknown-content",
                            "https://example.invalid/blob.bin",
                            b"binary-ish bytes",
                            content_type="application/octet-stream",
                        ),
                        warc_record(
                            "resource",
                            "urn:uuid:too-large",
                            "https://example.invalid/too-large.html",
                            b"<html>too large</html>",
                            content_type="text/html",
                        ),
                    ]
                )
            )
            config = load_warc_source_config(
                write_warc_config(
                    root / "warc.toml",
                    max_total_payload_bytes=8,
                )
            )

            manifest = build_warc_manifest(config, root_path=root, clock=fixed_clock)

        skip_reasons = {record.skip_reason for record in manifest.records}
        self.assertIn("empty-payload", skip_reasons)
        self.assertIn("continuation-deferred", skip_reasons)
        self.assertIn("unsupported-record-type", skip_reasons)
        self.assertIn("metadata-only", skip_reasons)
        self.assertIn("max_total_payload_bytes", skip_reasons)
        self.assertEqual(manifest.routed_payload_count, 0)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            artifact_dir = root / "warc_artifacts"
            artifact_dir.mkdir(parents=True)
            (artifact_dir / "example.warc").write_bytes(
                b"".join(
                    [
                        warc_record(
                            "resource",
                            "urn:uuid:xml",
                            "https://example.invalid/feed.xml",
                            b"<feed />",
                            content_type="application/xml",
                        ),
                        warc_record(
                            "resource",
                            "urn:uuid:first",
                            "https://example.invalid/first.html",
                            b"<html>first</html>",
                            content_type="text/html",
                        ),
                        warc_record(
                            "resource",
                            "urn:uuid:second",
                            "https://example.invalid/second.css",
                            b".second { color: blue; }",
                            content_type="text/css",
                        ),
                    ]
                )
            )
            config = load_warc_source_config(
                write_warc_config(
                    root / "warc-max-files.toml",
                    max_file_count=2,
                )
            )

            manifest = build_warc_manifest(config, root_path=root, clock=fixed_clock)

        self.assertEqual(manifest.routed_payload_count, 2)
        self.assertIn("max_file_count", {record.skip_reason for record in manifest.records})
