import unittest
from unittest.mock import patch

from repomap_kg.extractors.documents.email import (
    extract_eml_file_observations,
)
from repomap_kg.extractors.documents.email_common import (
    _is_secret_prone,
    _redact_url,
    _redacted_filename,
)
from repomap_kg.extractors.documents.feed import (
    extract_feed_file_observations,
)
from repomap_kg.extractors.documents.feed_support import (
    _parse_date,
    _reference_target,
    _safe_summary,
)


class EmailFeedExtractorBoundariesUnitTests(unittest.TestCase):
    def test_email_header_limits_and_address_normalization_boundaries(self):
        eml_bytes = (
            b"From: Normal User <user@example.com>\n"
            b"To: <user@>, @domain.com, missing-at, <real@sub.example.com>\n"
            b"Subject: Test email\n"
            b"Content-Type: text/plain\n\n"
            b"Body text\n"
        )
        with patch("repomap_kg.extractors.documents.email.MAX_HEADER_BYTES", 10):
            obs = extract_eml_file_observations("mail/test.eml", eml_bytes)
            error_kinds = {o.metadata["error_kind"] for o in obs if o.kind == "email.parse_error"}
            self.assertIn("header-size-limit", error_kinds)

        normal_obs = extract_eml_file_observations("mail/normal.eml", eml_bytes)
        addresses = [o for o in normal_obs if o.kind == "email.address"]
        domains = {a.metadata["address_domain"] for a in addresses}
        self.assertIn("example.com", domains)
        self.assertIn("sub.example.com", domains)

    def test_email_common_redaction_and_url_boundaries(self):
        # mailto without @
        self.assertIn("example.invalid", _redact_url("mailto:contact"))
        # mailto with secret-prone domain
        self.assertIn("example.invalid", _redact_url("mailto:alice@secret_token.com"))
        # URL with port
        port_redacted = _redact_url("https://example.com:8080/path?token=secret123&clean=value")
        self.assertIn(":8080", port_redacted)
        self.assertIn("token=REDACTED", port_redacted)
        self.assertIn("clean=value", port_redacted)

        # filename redactions
        self.assertIsNone(_redacted_filename(None))
        self.assertIsNone(_redacted_filename(""))
        self.assertEqual(_redacted_filename("no-extension"), "<redacted>")
        self.assertEqual(_redacted_filename("doc.pdf"), "<redacted>.pdf")

        # is_secret_prone
        self.assertFalse(_is_secret_prone(None))

    def test_feed_atom_and_json_fallback_identities(self):
        # Atom without id/link, with title
        atom_title_only = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Feed Title Only</title>
  <entry>
    <title>Entry 1</title>
    <updated>2026-08-26T12:00:00Z</updated>
  </entry>
</feed>"""
        obs = extract_feed_file_observations("feeds/atom_title.xml", atom_title_only)
        ch = next(o for o in obs if o.kind == "feed.channel")
        self.assertEqual(ch.metadata["identity_source"], "title+document")

        # Atom without id/link/title
        atom_no_title = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <summary>Summary text</summary>
  </entry>
</feed>"""
        obs2 = extract_feed_file_observations("feeds/atom_none.xml", atom_no_title)
        ch2 = next(o for o in obs2 if o.kind == "feed.channel")
        self.assertEqual(ch2.metadata["identity_source"], "document")

        # JSON feed with title only
        json_title_only = """{
  "version": "https://jsonfeed.org/version/1.1",
  "title": "JSON Feed Title Only",
  "items": [
    {
      "id": "1",
      "attachments": ["not-a-dict", {"mime_type": "audio/mp3"}],
      "authors": ["not-a-dict", {"avatar": "http://img"}]
    }
  ]
}"""
        obs3 = extract_feed_file_observations("feeds/json_title.json", json_title_only)
        ch3 = next(o for o in obs3 if o.kind == "feed.channel")
        self.assertEqual(ch3.metadata["identity_source"], "title+document")

        from repomap_kg.extractors.documents.feed_data import _json_channel_info
        from repomap_kg.graph.keys import feed_document_key
        doc_key = feed_document_key("feeds/j.json")
        # home_page_url only
        ch_home = _json_channel_info("feeds/j.json", doc_key, {"home_page_url": "https://example.com"})
        self.assertEqual(ch_home["identity_source"], "home_page_url")
        # neither
        ch_none = _json_channel_info("feeds/j.json", doc_key, {})
        self.assertEqual(ch_none["identity_source"], "document")

    def test_feed_support_reference_and_summary_boundaries(self):
        self.assertIn("missing-target", _reference_target("feeds/feed.xml", "  "))
        self.assertIsNone(_parse_date("   "))
        # naive datetime
        self.assertEqual(_parse_date("2026-08-26 12:00:00"), "2026-08-26T12:00:00Z")
        # HTML stripped to empty
        self.assertIsNone(_safe_summary("<p>   <br/> </p>"))
        # summary length truncation
        long_text = "word " * 60
        summary = _safe_summary(long_text)
        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertTrue(summary.endswith("..."))

    def test_feed_and_email_defects_and_invalid_payloads(self):
        # Non-dict JSON feed
        obs = extract_feed_file_observations("feeds/list.json", "[1, 2, 3]")
        self.assertEqual(obs, ())

        # Email with defective headers
        bad_mime = b"Content-Type: ?invalid?mime\nSubject: =?utf-8?B?bad_base64?=\n\nBody\n"
        obs_email = extract_eml_file_observations("mail/defective.eml", bad_mime)
        self.assertTrue(len(obs_email) > 0)


if __name__ == "__main__":
    unittest.main()
