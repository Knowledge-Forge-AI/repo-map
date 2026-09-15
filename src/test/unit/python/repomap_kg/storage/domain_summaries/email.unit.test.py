import unittest
import os
from types import SimpleNamespace
from unittest.mock import patch

from repomap_kg.storage import (
    StorageSchemaError,
    query_email_summary,
)
from repomap_kg.storage.readback_driver import PG_CONNECTOR_ENV, READBACK_DRIVER_ENV

class StorageDomainEmailSummaryUnitTests(unittest.TestCase):
    def test_query_email_summary_returns_safe_counts(self):
        completed = SimpleNamespace(
            stdout=(
                '{"root_path":"/tmp/fixture",'
                '"repository_name":"fixture",'
                '"mailboxes":1,'
                '"messages":10,'
                '"eml_messages":8,'
                '"mbox_messages":2,'
                '"addresses":6,'
                '"address_observations":12,'
                '"address_domains":1,'
                '"mime_parts":22,'
                '"text_plain_parts":9,'
                '"text_html_parts":4,'
                '"attachment_stubs":3,'
                '"inline_attachments":1,'
                '"content_id_parts":1,'
                '"thread_hints":5,'
                '"message_references":4,'
                '"external_url_references":1,'
                '"list_unsubscribe_references":1,'
                '"parse_errors":2,'
                '"malformed_or_oversized_diagnostics":2,'
                '"message_id_present":9,'
                '"message_id_missing_or_invalid":1,'
                '"messages_with_attachments":2,'
                '"messages_with_html":4,'
                '"messages_with_plain":9,'
                '"mailbox_limits":1,'
                '"no_provider_api":true,'
                '"no_mutation":true,'
                '"no_body_text":true,'
                '"no_attachment_content":true}\n'
            )
        )

        with patch.dict(
            os.environ,
            {PG_CONNECTOR_ENV: "psql", READBACK_DRIVER_ENV: "psql"},
        ), patch(
            "repomap_kg.storage.subprocess.run", return_value=completed
        ) as run:
            summary = query_email_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                psql_command="/bin/psql",
            )

        self.assertEqual(summary.repository_name, "fixture")
        self.assertEqual(summary.mailboxes, 1)
        self.assertEqual(summary.messages, 10)
        self.assertEqual(summary.eml_messages, 8)
        self.assertEqual(summary.mbox_messages, 2)
        self.assertEqual(summary.address_domains, 1)
        self.assertEqual(summary.text_html_parts, 4)
        self.assertEqual(summary.attachment_stubs, 3)
        self.assertEqual(summary.message_references, 4)
        self.assertEqual(summary.list_unsubscribe_references, 1)
        self.assertEqual(summary.message_id_missing_or_invalid, 1)
        self.assertEqual(summary.mailbox_limits, 1)
        self.assertTrue(summary.no_provider_api)
        self.assertTrue(summary.no_mutation)
        self.assertTrue(summary.no_body_text)
        self.assertTrue(summary.no_attachment_content)
        self.assertIn("-qAt", run.call_args.args[0])
        self.assertIn("canonical_nodes.kind LIKE 'email.%'", run.call_args.kwargs["input"])
    def test_query_email_summary_rejects_malformed_json(self):
        completed = SimpleNamespace(stdout='{"root_path": "/tmp/fixture"}\n')

        with patch.dict(
            os.environ,
            {PG_CONNECTOR_ENV: "psql", READBACK_DRIVER_ENV: "psql"},
        ), patch(
            "repomap_kg.storage.subprocess.run", return_value=completed
        ):
            with self.assertRaisesRegex(StorageSchemaError, "email summary"):
                query_email_summary(["-d", "postgres"], root_path="/tmp/fixture")
