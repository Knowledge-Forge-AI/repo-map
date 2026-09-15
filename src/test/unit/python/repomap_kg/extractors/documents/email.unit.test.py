import unittest

from repomap_kg.extractors.documents.email import (
    MAX_EML_BYTES,
    extract_eml_file_observations,
)
SIMPLE_EML = b"""Message-ID: <single-message@example.invalid>
Date: Tue, 30 Jun 2026 12:34:56 +0000
From: Example Sender <alice@example.invalid>
To: Example Receiver <bob@example.invalid>
Cc: Example Copy <copy@example.invalid>
Reply-To: Replies <reply@example.invalid>
Subject: Quarterly planning code
Content-Type: text/plain; charset=utf-8
Content-Transfer-Encoding: 7bit

This body text must not appear in observations.
"""


THREAD_REPLY_EML = b"""Message-ID: <reply-message@example.invalid>
Date: Tue, 30 Jun 2026 13:00:00 +0000
From: Example Receiver <bob@example.invalid>
To: Example Sender <alice@example.invalid>
Subject: Re: Quarterly planning code
In-Reply-To: <single-message@example.invalid>
References: <root-message@example.invalid> <single-message@example.invalid>
Content-Type: text/plain; charset=utf-8

Reply body text must not leak.
"""


MULTIPART_ATTACHMENT_EML = b"""Message-ID: <attachment-message@example.invalid>
Date: Tue, 30 Jun 2026 14:00:00 +0000
From: Attachments <alice@example.invalid>
To: Receiver <bob@example.invalid>
Subject: Attachment fixture
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="mix-boundary"

--mix-boundary
Content-Type: multipart/alternative; boundary="alt-boundary"

--alt-boundary
Content-Type: text/plain; charset=utf-8

Plain body text must not leak.
--alt-boundary
Content-Type: text/html; charset=utf-8

<html><body><script>hidden()</script>HTML body must not leak.</body></html>
--alt-boundary--

--mix-boundary
Content-Type: text/plain
Content-Disposition: attachment; filename="invoice-secret-code.txt"
Content-Transfer-Encoding: base64

c2Vuc2l0aXZlIGF0dGFjaG1lbnQgYm9keQ==
--mix-boundary--
"""


REDACTION_EML = b"""Message-ID: <redaction-message@example.invalid>
Date: Tue, 30 Jun 2026 15:00:00 +0000
From: Secret Sender <secret.sender@example.invalid>
To: Secret Receiver <secret.receiver@example.invalid>
Subject: reset_code fake-mail-reset-code
List-Unsubscribe: <https://example.invalid/unsubscribe?token=fake-mail-token>, <mailto:unsubscribe-secret@example.invalid>
Content-Type: text/plain; charset=utf-8

fake-mail-body-secret
"""


INLINE_CID_EML = b"""Message-ID: <inline-cid-message@example.invalid>
Date: not a real date
From: Inline Sender <alice@example.invalid>
To: Inline Receiver <bob@example.invalid>
Subject: Inline CID fixture
MIME-Version: 1.0
Content-Type: multipart/related; boundary="rel-boundary"

--rel-boundary
Content-Type: text/html; charset=utf-8

<html><body><img src="cid:diagram@example.invalid">Inline body must not leak.</body></html>
--rel-boundary
Content-Type: image/png
Content-Disposition: inline; filename="inline-diagram.png"
Content-ID: <diagram@example.invalid>
Content-Transfer-Encoding: base64

iVBORw0KGgo=
--rel-boundary--
"""


class EmailExtractorUnitTests(unittest.TestCase):
    def test_extracts_safe_message_headers_addresses_and_body_part_metadata(self):
        observations = extract_eml_file_observations(
            "mail/single-message.eml",
            SIMPLE_EML,
        )
        payload = "\n".join(item.to_json_line() for item in observations)
        kinds = {item.kind for item in observations}
        message = next(item for item in observations if item.kind == "email.message")
        addresses = [item for item in observations if item.kind == "email.address"]
        parts = [item for item in observations if item.kind == "email.part"]

        self.assertIn("email.message", kinds)
        self.assertIn("email.header", kinds)
        self.assertIn("email.address", kinds)
        self.assertIn("email.part", kinds)
        self.assertEqual(message.metadata["format"], "eml")
        self.assertTrue(message.metadata["message_id_present"])
        self.assertTrue(message.metadata["message_id_valid"])
        self.assertRegex(message.metadata["message_id_hash"], r"^[0-9a-f]{64}$")
        self.assertEqual(message.metadata["subject_present"], True)
        self.assertRegex(message.metadata["subject_hash"], r"^[0-9a-f]{64}$")
        self.assertEqual(message.metadata["subject_preview_redacted"], "<redacted>")
        self.assertEqual(message.metadata["from_count"], 1)
        self.assertEqual(message.metadata["to_count"], 1)
        self.assertEqual(message.metadata["cc_count"], 1)
        self.assertEqual(message.metadata["reply_to_count"], 1)
        self.assertEqual(message.metadata["has_text_plain"], True)
        self.assertEqual(message.metadata["has_text_html"], False)
        self.assertEqual(parts[0].metadata["content_type"], "text/plain")
        self.assertEqual(parts[0].metadata["charset"], "utf-8")
        self.assertTrue(all("address_hash" in item.metadata for item in addresses))
        self.assertEqual(
            {item.metadata["address_domain"] for item in addresses},
            {"example.invalid"},
        )
        self.assertNotIn("alice@example.invalid", payload)
        self.assertNotIn("bob@example.invalid", payload)
        self.assertNotIn("Example Sender", payload)
        self.assertNotIn("Quarterly planning code", payload)
        self.assertNotIn("This body text must not appear", payload)

    def test_extracts_thread_hints_and_references_without_raw_message_ids(self):
        observations = extract_eml_file_observations(
            "mail/thread-reply.eml",
            THREAD_REPLY_EML,
        )
        payload = "\n".join(item.to_json_line() for item in observations)
        hints = [item for item in observations if item.kind == "email.thread_hint"]
        references = [item for item in observations if item.kind == "email.reference"]

        self.assertEqual(
            [item.metadata["thread_hint_kind"] for item in hints],
            ["in_reply_to", "references", "references"],
        )
        self.assertTrue(all(item.metadata["reference_kind"] in {"in_reply_to", "references"} for item in references))
        self.assertTrue(all(item.metadata["not_fetched"] for item in references))
        targets = [item.target for item in references if item.target is not None]
        self.assertEqual(len(targets), len(references))
        self.assertTrue(all(target.startswith("email.message:") or target.startswith("unknown:email-message:") for target in targets))
        self.assertNotIn("single-message@example.invalid", payload)
        self.assertNotIn("root-message@example.invalid", payload)
        self.assertNotIn("Reply body text", payload)

    def test_extracts_mime_part_tree_and_attachment_stubs_only(self):
        observations = extract_eml_file_observations(
            "mail/attachment-stub.eml",
            MULTIPART_ATTACHMENT_EML,
        )
        payload = "\n".join(item.to_json_line() for item in observations)
        message = next(item for item in observations if item.kind == "email.message")
        attachments = [
            item for item in observations if item.kind == "email.attachment_stub"
        ]
        parts = [item for item in observations if item.kind == "email.part"]

        self.assertEqual(message.metadata["text_plain_part_count"], 1)
        self.assertEqual(message.metadata["text_html_part_count"], 1)
        self.assertEqual(message.metadata["attachment_count"], 1)
        self.assertTrue(message.metadata["has_attachments"])
        self.assertGreaterEqual(len(parts), 3)
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].metadata["attachment_filename_redacted"], "<redacted>.txt")
        self.assertRegex(attachments[0].metadata["attachment_filename_hash"], r"^[0-9a-f]{64}$")
        self.assertEqual(attachments[0].metadata["attachment_mime_type"], "text/plain")
        self.assertNotIn("invoice-secret-code.txt", payload)
        self.assertNotIn("sensitive attachment body", payload)
        self.assertNotIn("HTML body must not leak", payload)
        self.assertNotIn("<script>", payload)

    def test_redacts_subject_addresses_header_urls_and_secret_markers(self):
        observations = extract_eml_file_observations(
            "mail/redaction.eml",
            REDACTION_EML,
        )
        payload = "\n".join(item.to_json_line() for item in observations)
        message = next(item for item in observations if item.kind == "email.message")

        self.assertTrue(message.metadata["redacted"])
        self.assertEqual(message.metadata["subject_preview_redacted"], "<redacted>")
        self.assertNotIn("fake-mail-reset-code", payload)
        self.assertNotIn("fake-mail-token", payload)
        self.assertNotIn("fake-mail-body-secret", payload)
        self.assertNotIn("secret.sender@example.invalid", payload)
        self.assertNotIn("unsubscribe-secret@example.invalid", payload)
        self.assertIn("REDACTED", payload)
        self.assertIn("mailto:redacted@example.invalid", payload)

    def test_reports_parse_diagnostics_for_missing_or_invalid_message_identity(self):
        observations = extract_eml_file_observations(
            "mail/malformed.eml",
            b"From: bad@example.invalid\nSubject: no message identity\n\nbody\n",
        )
        kinds = {item.kind for item in observations}
        message = next(item for item in observations if item.kind == "email.message")

        self.assertIn("email.parse_error", kinds)
        self.assertFalse(message.metadata["message_id_valid"])
        self.assertEqual(message.metadata["identity_strength"], "structural")

    def test_records_inline_cid_stubs_invalid_date_and_file_size_limit(self):
        observations = extract_eml_file_observations(
            "mail/inline-cid.eml",
            INLINE_CID_EML,
        )
        payload = "\n".join(item.to_json_line() for item in observations)
        message = next(item for item in observations if item.kind == "email.message")
        inline_stub = next(
            item for item in observations if item.kind == "email.attachment_stub"
        )
        oversized = extract_eml_file_observations(
            "mail/too-large.eml",
            b"x" * (MAX_EML_BYTES + 1),
        )

        self.assertEqual(message.metadata["date_parse_status"], "invalid")
        self.assertTrue(inline_stub.metadata["inline"])
        self.assertTrue(inline_stub.metadata["content_id_present"])
        self.assertEqual(inline_stub.metadata["attachment_filename_redacted"], "<redacted>.png")
        self.assertEqual(oversized[0].kind, "email.parse_error")
        self.assertEqual(oversized[0].metadata["error_kind"], "file-size-limit")
        self.assertNotIn("diagram@example.invalid", payload)
        self.assertNotIn("Inline body must not leak", payload)


if __name__ == "__main__":
    unittest.main()
