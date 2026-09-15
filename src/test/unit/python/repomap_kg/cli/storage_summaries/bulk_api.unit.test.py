import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from repomap_kg.cli import main
from repomap_kg.storage import (
    APISummaryRecord,
    BulkSummaryRecord,
)


class CliStorageBulkApiSummaryUnitTests(unittest.TestCase):
    def test_storage_bulk_summary_prints_json_record(self):
        summary = BulkSummaryRecord(
            root_path_summary=".",
            repository_name="fixture",
            bulk_runs=2,
            sources=2,
            source_ids=("email-export", "mixed-corpus"),
            corpus_kinds={"email_export": 1, "mixed_corpus": 1},
            policy_statuses={"allowed_with_limits": 2},
            file_count_included=12,
            file_count_skipped=5,
            total_bytes_included=4096,
            extractor_counts={"eml": 3, "javascript": 1},
            skip_reasons={"archive_deferred": 1, "hidden_excluded": 1},
            diagnostic_counts={"extractor_error": 1},
            redaction_counts={"raw_observations": 2},
            limit_hit_count=1,
            max_files_hit_count=1,
            max_total_bytes_hit_count=0,
            max_file_bytes_hit_count=0,
            max_depth_hit_count=0,
            archive_deferred=1,
            warc_deferred=0,
            email_export_runs=1,
            mixed_corpus_runs=1,
            observations_with_bulk_provenance=42,
            no_provider_api=True,
            no_external_fetch=True,
            no_source_mutation=True,
            no_archive_decompression=True,
        )
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_bulk_summary",
            return_value=summary,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "bulk-summary",
                        "--root-path",
                        "/tmp/fixture",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["root_path_summary"], ".")
        self.assertEqual(payload["bulk_runs"], 2)
        self.assertEqual(payload["source_ids"], ["email-export", "mixed-corpus"])
        self.assertEqual(payload["corpus_kinds"]["mixed_corpus"], 1)
        self.assertEqual(payload["skip_reasons"]["archive_deferred"], 1)
        self.assertEqual(payload["observations_with_bulk_provenance"], 42)
        self.assertTrue(payload["no_provider_api"])
        self.assertTrue(payload["no_external_fetch"])
        self.assertTrue(payload["no_source_mutation"])
        self.assertTrue(payload["no_archive_decompression"])
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")

    def test_storage_bulk_summary_prints_table_record(self):
        summary = BulkSummaryRecord(
            root_path_summary=".",
            repository_name="fixture",
            bulk_runs=1,
            sources=1,
            source_ids=("mixed-corpus",),
            corpus_kinds={"mixed_corpus": 1},
            policy_statuses={"allowed_with_limits": 1},
            file_count_included=6,
            file_count_skipped=2,
            total_bytes_included=2048,
            extractor_counts={"javascript": 1},
            skip_reasons={"excluded_directory": 1},
            diagnostic_counts={},
            redaction_counts={},
            limit_hit_count=0,
            max_files_hit_count=0,
            max_total_bytes_hit_count=0,
            max_file_bytes_hit_count=0,
            max_depth_hit_count=0,
            archive_deferred=0,
            warc_deferred=0,
            email_export_runs=0,
            mixed_corpus_runs=1,
            observations_with_bulk_provenance=12,
            no_provider_api=True,
            no_external_fetch=True,
            no_source_mutation=True,
            no_archive_decompression=True,
        )
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_bulk_summary",
            return_value=summary,
        ):
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "bulk-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertIn("bulk_runs", stdout.getvalue())
        self.assertIn("source_ids", stdout.getvalue())
        self.assertIn("mixed_corpus=1", stdout.getvalue())
        self.assertIn("no_archive_decompression", stdout.getvalue())

    def test_storage_api_summary_prints_json_record(self):
        summary = APISummaryRecord(
            root_path_summary=".",
            repository_name="fixture",
            api_runs=1,
            sources=1,
            source_ids=("fixture-readonly-api",),
            source_types={"api.rest": 1},
            api_source_classes={"api.custom_documented_api": 1},
            provider_names={"Fixture Provider": 1},
            provider_products={"Fixture API": 1},
            policy_statuses={"allowed_with_limits": 1},
            requests=1,
            responses=1,
            endpoints=1,
            endpoint_names=("items",),
            methods={"GET": 1},
            downstream_routes={"config": 1},
            response_types={"application/json": 1},
            response_byte_count=512,
            redacted_responses=1,
            diagnostic_counts={},
            routed_artifacts=1,
            observations_with_api_provenance=7,
            config_documents_from_api=1,
            no_network=True,
            no_mutation=True,
            no_credentials_resolved=True,
            no_scheduler=True,
            no_provider_specific_behavior=True,
        )
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_api_summary",
            return_value=summary,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "api-summary",
                        "--root-path",
                        "/tmp/fixture",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["root_path_summary"], ".")
        self.assertEqual(payload["api_runs"], 1)
        self.assertEqual(payload["source_ids"], ["fixture-readonly-api"])
        self.assertEqual(payload["provider_names"]["Fixture Provider"], 1)
        self.assertEqual(payload["methods"]["GET"], 1)
        self.assertEqual(payload["observations_with_api_provenance"], 7)
        self.assertTrue(payload["no_network"])
        self.assertTrue(payload["no_mutation"])
        self.assertTrue(payload["no_credentials_resolved"])
        self.assertTrue(payload["no_scheduler"])
        self.assertTrue(payload["no_provider_specific_behavior"])
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")

    def test_storage_api_summary_prints_table_record(self):
        summary = APISummaryRecord(
            root_path_summary=".",
            repository_name="fixture",
            api_runs=1,
            sources=1,
            source_ids=("fixture-readonly-api",),
            source_types={"api.rest": 1},
            api_source_classes={"api.custom_documented_api": 1},
            provider_names={"Fixture Provider": 1},
            provider_products={"Fixture API": 1},
            policy_statuses={"allowed_with_limits": 1},
            requests=1,
            responses=1,
            endpoints=1,
            endpoint_names=("items",),
            methods={"GET": 1},
            downstream_routes={"config": 1},
            response_types={"application/json": 1},
            response_byte_count=512,
            redacted_responses=1,
            diagnostic_counts={},
            routed_artifacts=1,
            observations_with_api_provenance=7,
            config_documents_from_api=1,
            no_network=True,
            no_mutation=True,
            no_credentials_resolved=True,
            no_scheduler=True,
            no_provider_specific_behavior=True,
        )
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_api_summary",
            return_value=summary,
        ):
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "api-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertIn("api_runs", stdout.getvalue())
        self.assertIn("source_ids", stdout.getvalue())
        self.assertIn("api.rest=1", stdout.getvalue())
        self.assertIn("Fixture Provider=1", stdout.getvalue())
        self.assertIn("no_provider_specific_behavior", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
