import unittest

from repomap_kg.storage import (
    APISummaryRecord,
    BulkSummaryRecord,
    CanonicalStorageSummaryRecord,
    EmailSummaryRecord,
    format_api_summary_table,
    format_bulk_summary_table,
    format_canonical_storage_summary_table,
    format_email_summary_table,
)


class StorageSourceSummaryTableUnitTests(unittest.TestCase):
    def test_format_canonical_storage_summary_table_uses_count_columns(self):
        table = format_canonical_storage_summary_table(
            CanonicalStorageSummaryRecord(
                root_path="/tmp/fixture",
                repository_name="fixture",
                latest_run_id=11,
                runs=1,
                files=2,
                raw_observations=4,
                raw_observations_total=4,
                latest_run_raw_observations=2,
                canonical_nodes=6,
                canonical_edges=7,
                canonical_evidence=8,
            )
        )

        self.assertIn("root_path", table)
        self.assertIn("latest_run_id", table)
        self.assertIn("raw_observations_total", table)
        self.assertIn("latest_run_raw_observations", table)
        self.assertIn("canonical_nodes", table)
        self.assertIn("canonical_edges", table)
        self.assertIn("/tmp/fixture", table)

    def test_format_email_summary_table_uses_privacy_and_readback_columns(self):
        table = format_email_summary_table(
            EmailSummaryRecord(
                root_path="/tmp/fixture",
                repository_name="fixture",
                mailboxes=1,
                messages=10,
                eml_messages=8,
                mbox_messages=2,
                addresses=6,
                address_observations=12,
                address_domains=1,
                mime_parts=22,
                text_plain_parts=9,
                text_html_parts=4,
                attachment_stubs=3,
                inline_attachments=1,
                content_id_parts=1,
                thread_hints=5,
                message_references=4,
                external_url_references=1,
                list_unsubscribe_references=1,
                parse_errors=2,
                malformed_or_oversized_diagnostics=2,
                message_id_present=9,
                message_id_missing_or_invalid=1,
                messages_with_attachments=2,
                messages_with_html=4,
                messages_with_plain=9,
                mailbox_limits=1,
                no_provider_api=True,
                no_mutation=True,
                no_body_text=True,
                no_attachment_content=True,
            )
        )

        self.assertIn("mailboxes", table)
        self.assertIn("messages", table)
        self.assertIn("mbox_messages", table)
        self.assertIn("attachment_stubs", table)
        self.assertIn("list_unsubscribe_references", table)
        self.assertIn("no_provider_api", table)
        self.assertIn("no_attachment_content", table)

    def test_format_bulk_summary_table_uses_manifest_and_safety_columns(self):
        table = format_bulk_summary_table(
            BulkSummaryRecord(
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
        )

        self.assertIn("bulk_runs", table)
        self.assertIn("source_ids", table)
        self.assertIn("mixed_corpus=1", table)
        self.assertIn("archive_deferred=1", table)
        self.assertIn("observations_with_bulk_provenance", table)
        self.assertIn("no_archive_decompression", table)

    def test_format_api_summary_table_uses_manifest_and_safety_columns(self):
        table = format_api_summary_table(
            APISummaryRecord(
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
        )

        self.assertIn("api_runs", table)
        self.assertIn("source_ids", table)
        self.assertIn("api.rest=1", table)
        self.assertIn("Fixture Provider=1", table)
        self.assertIn("GET=1", table)
        self.assertIn("observations_with_api_provenance", table)
        self.assertIn("no_provider_specific_behavior", table)
