import unittest

from repomap_kg.storage import (
    api_summary_from_storage_payload,
    js_summary_from_storage_payload,
    ruby_summary_from_storage_payload,
    email_summary_from_storage_payload,
    api_summary_to_jsonable,
    bulk_summary_from_storage_payload,
    bulk_summary_to_jsonable,
    js_summary_to_jsonable,
    ruby_summary_to_jsonable,
    email_summary_to_jsonable,
)

class StorageSourcePayloadParserUnitTests(unittest.TestCase):
    def test_email_summary_payload_parser_preserves_safe_counts(self):
        summary = email_summary_from_storage_payload(
            {
                "root_path": "/tmp/fixture",
                "repository_name": "fixture",
                "mailboxes": 1,
                "messages": 10,
                "eml_messages": 8,
                "mbox_messages": 2,
                "addresses": 6,
                "address_observations": 12,
                "address_domains": 1,
                "mime_parts": 22,
                "text_plain_parts": 9,
                "text_html_parts": 4,
                "attachment_stubs": 3,
                "inline_attachments": 1,
                "content_id_parts": 1,
                "thread_hints": 5,
                "message_references": 4,
                "external_url_references": 1,
                "list_unsubscribe_references": 1,
                "parse_errors": 2,
                "malformed_or_oversized_diagnostics": 2,
                "message_id_present": 9,
                "message_id_missing_or_invalid": 1,
                "messages_with_attachments": 2,
                "messages_with_html": 4,
                "messages_with_plain": 9,
                "mailbox_limits": 1,
                "no_provider_api": True,
                "no_mutation": True,
                "no_body_text": True,
                "no_attachment_content": True,
            }
        )

        self.assertEqual(summary.root_path, "/tmp/fixture")
        self.assertEqual(summary.mailboxes, 1)
        self.assertEqual(summary.messages, 10)
        self.assertEqual(summary.address_observations, 12)
        self.assertEqual(summary.content_id_parts, 1)
        self.assertEqual(summary.malformed_or_oversized_diagnostics, 2)
        self.assertTrue(summary.no_body_text)
        self.assertEqual(email_summary_to_jsonable(summary), summary.to_dict())
    def test_bulk_summary_payload_parser_preserves_safe_counts(self):
        summary = bulk_summary_from_storage_payload(
            {
                "root_path_summary": ".",
                "repository_name": "fixture",
                "bulk_runs": 2,
                "sources": 2,
                "source_ids": ["email-export", "mixed-corpus"],
                "corpus_kinds": {"email_export": 1, "mixed_corpus": 1},
                "policy_statuses": {"allowed_with_limits": 2},
                "file_count_included": 12,
                "file_count_skipped": 5,
                "total_bytes_included": 4096,
                "extractor_counts": {"eml": 3, "javascript": 1},
                "skip_reasons": {"archive_deferred": 1, "hidden_excluded": 1},
                "diagnostic_counts": {"extractor_error": 1},
                "redaction_counts": {"raw_observations": 2},
                "limit_hit_count": 1,
                "max_files_hit_count": 1,
                "max_total_bytes_hit_count": 0,
                "max_file_bytes_hit_count": 0,
                "max_depth_hit_count": 0,
                "archive_deferred": 1,
                "warc_deferred": 0,
                "email_export_runs": 1,
                "mixed_corpus_runs": 1,
                "observations_with_bulk_provenance": 42,
                "no_provider_api": True,
                "no_external_fetch": True,
                "no_source_mutation": True,
                "no_archive_decompression": True,
            }
        )

        self.assertEqual(summary.source_ids, ("email-export", "mixed-corpus"))
        self.assertEqual(summary.corpus_kinds["mixed_corpus"], 1)
        self.assertEqual(summary.extractor_counts["eml"], 3)
        self.assertEqual(summary.skip_reasons["archive_deferred"], 1)
        self.assertEqual(summary.observations_with_bulk_provenance, 42)
        self.assertTrue(summary.no_archive_decompression)
        self.assertEqual(bulk_summary_to_jsonable(summary), summary.to_dict())
    def test_api_summary_payload_parser_preserves_safe_counts(self):
        summary = api_summary_from_storage_payload(
            {
                "root_path_summary": ".",
                "repository_name": "fixture",
                "api_runs": 1,
                "sources": 1,
                "source_ids": ["fixture-readonly-api"],
                "source_types": {"api.rest": 1},
                "api_source_classes": {"api.custom_documented_api": 1},
                "provider_names": {"Fixture Provider": 1},
                "provider_products": {"Fixture API": 1},
                "policy_statuses": {"allowed_with_limits": 1},
                "requests": 1,
                "responses": 1,
                "endpoints": 1,
                "endpoint_names": ["items"],
                "methods": {"GET": 1},
                "downstream_routes": {"config": 1},
                "response_types": {"application/json": 1},
                "response_byte_count": 512,
                "redacted_responses": 1,
                "diagnostic_counts": {},
                "routed_artifacts": 1,
                "observations_with_api_provenance": 7,
                "config_documents_from_api": 1,
                "no_network": True,
                "no_mutation": True,
                "no_credentials_resolved": True,
                "no_scheduler": True,
                "no_provider_specific_behavior": True,
            }
        )

        self.assertEqual(summary.source_ids, ("fixture-readonly-api",))
        self.assertEqual(summary.provider_names["Fixture Provider"], 1)
        self.assertEqual(summary.endpoint_names, ("items",))
        self.assertEqual(summary.methods["GET"], 1)
        self.assertEqual(summary.observations_with_api_provenance, 7)
        self.assertTrue(summary.no_credentials_resolved)
        self.assertEqual(api_summary_to_jsonable(summary), summary.to_dict())
    def test_js_summary_payload_parser_preserves_safe_counts(self):
        summary = js_summary_from_storage_payload(
            {
                "root_path": "/tmp/fixture",
                "repository_name": "fixture",
                "js_files": 5,
                "modules": 5,
                "functions": 2,
                "classes": 1,
                "methods": 1,
                "variables": 4,
                "components": 3,
                "routes": 2,
                "test_suites": 1,
                "test_cases": 2,
                "references": 8,
                "imports": 4,
                "exports": 3,
                "hooks": 2,
                "test_expectations": 2,
                "source_map_references": 1,
                "frontend_asset_files": 1,
                "saved_page_asset_files": 0,
                "test_report_asset_files": 1,
                "dynamic_diagnostics": 3,
                "parse_errors": 0,
                "profile_counts": {"jest": 1, "react": 2},
                "no_execution": True,
            }
        )

        self.assertEqual(summary.root_path, "/tmp/fixture")
        self.assertEqual(summary.profile_counts, {"jest": 1, "react": 2})
        self.assertEqual(summary.components, 3)
        self.assertEqual(summary.source_map_references, 1)
        self.assertTrue(summary.no_execution)
        self.assertEqual(js_summary_to_jsonable(summary), summary.to_dict())
    def test_ruby_summary_payload_parser_preserves_safe_counts(self):
        summary = ruby_summary_from_storage_payload(
            {
                "root_path": "/tmp/fixture",
                "repository_name": "fixture",
                "ruby_files": 3,
                "modules": 1,
                "classes": 2,
                "methods": 4,
                "singleton_methods": 1,
                "constants": 2,
                "routes": 3,
                "test_cases": 1,
                "test_methods": 2,
                "references": 5,
                "gem_dependencies": 4,
                "vagrant_configs": 3,
                "rake_tasks": 2,
                "rake_namespaces": 1,
                "dynamic_diagnostics": 2,
                "parse_errors": 0,
                "profile_counts": {"minitest": 1, "sinatra": 1},
                "no_execution": True,
            }
        )

        self.assertEqual(summary.root_path, "/tmp/fixture")
        self.assertEqual(summary.profile_counts, {"minitest": 1, "sinatra": 1})
        self.assertEqual(summary.test_methods, 2)
        self.assertTrue(summary.no_execution)
        self.assertEqual(ruby_summary_to_jsonable(summary), summary.to_dict())
