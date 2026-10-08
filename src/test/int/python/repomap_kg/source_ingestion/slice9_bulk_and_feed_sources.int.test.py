import tempfile
import unittest
from pathlib import Path

from repomap_kg.ops.ingestion.bulk import (
    BulkPolicyError,
    build_bulk_plan,
    classify_bulk_route,
    load_bulk_source_config,
)
from repomap_kg.ops.ingestion.source_common import SourcePolicyError
from repomap_kg.ops.ingestion.source_feed import load_feed_source_config
from repomap_kg.ops.ingestion.source_warc import (
    _next_warc_record,
    _parse_header_lines,
    _parse_http_message_payload,
    _safe_warc_headers,
    _warc_payload_route,
    _warc_target,
)
from repomap_test_support.source_ingestion_integration import (
    bulk_fixture_root,
    source_fixture,
)


class Slice9BulkAndFeedSourcesIntegrationTests(unittest.TestCase):
    """Integration slice 9 tests covering bulk traversal, feed sources, and WARC parsing."""

    def test_s9_b08_bulk_route_classification_and_unsupported_skips(self) -> None:
        """Route classification assigns expected routes and skips unsupported extensions."""
        self.assertEqual(classify_bulk_route(Path("file.eml")), "eml")
        self.assertEqual(classify_bulk_route(Path("file.mbox")), "mbox")
        self.assertEqual(classify_bulk_route(Path("doc.md")), "markdown")
        self.assertEqual(classify_bulk_route(Path("cfg.json")), "config")
        self.assertEqual(classify_bulk_route(Path("index.html")), "html")
        self.assertEqual(classify_bulk_route(Path("style.css")), "css")
        self.assertEqual(classify_bulk_route(Path("code.ts")), "javascript")
        self.assertEqual(classify_bulk_route(Path("Rakefile")), "ruby")
        self.assertEqual(classify_bulk_route(Path("archive.warc.gz")), "warc")
        self.assertEqual(classify_bulk_route(Path("archive.zip")), "archive")
        self.assertIsNone(classify_bulk_route(Path("binary.exe")))

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg_path = root / "bulk.toml"
            cfg_path.write_text(
                (bulk_fixture_root() / "mixed_corpus" / "bulk.toml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (root / "valid.py").write_text("x = 1\n", encoding="utf-8")
            (root / "invalid.exe").write_bytes(b"\x00\x01\x02")

            config = load_bulk_source_config(cfg_path)
            manifest = build_bulk_plan(config, repository_root=root)
            included_names = [f.relative_path for f in manifest.included_files]
            skipped_reasons = {f.relative_path: f.reason for f in manifest.skipped_files}

            self.assertIn("valid.py", included_names)
            self.assertIn("invalid.exe", skipped_reasons)
            self.assertEqual(skipped_reasons["invalid.exe"], "unsupported_extension")

    def test_s9_b09_bulk_tree_walk_exclusions_and_limits(self) -> None:
        """Bulk directory walk enforces exclusions, depth boundaries, and byte/file limits."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg_text = (bulk_fixture_root() / "mixed_corpus" / "bulk.toml").read_text(
                encoding="utf-8"
            )
            cfg_text = cfg_text.replace("max_files = 100", "max_files = 1")
            cfg_text = cfg_text.replace("max_depth = 8", "max_depth = 1")
            cfg_path = root / "bulk.toml"
            cfg_path.write_text(cfg_text, encoding="utf-8")

            (root / ".hidden.py").write_text("x = 1\n", encoding="utf-8")
            (root / "file1.py").write_text("a = 1\n", encoding="utf-8")
            (root / "file2.py").write_text("b = 2\n", encoding="utf-8")
            deep_dir = root / "sub1" / "sub2"
            deep_dir.mkdir(parents=True)
            (deep_dir / "deep.py").write_text("c = 3\n", encoding="utf-8")

            config = load_bulk_source_config(cfg_path)
            manifest = build_bulk_plan(config, repository_root=root)
            reasons = {f.relative_path: f.reason for f in manifest.skipped_files}

            self.assertEqual(len(manifest.included_files), 1)
            self.assertIn(".hidden.py", reasons)
            self.assertEqual(reasons[".hidden.py"], "hidden_excluded")
            self.assertIn("sub1/sub2/deep.py", reasons)
            self.assertEqual(reasons["sub1/sub2/deep.py"], "max_depth_exceeded")
            self.assertTrue(any("max_files_exceeded" in r for r in reasons.values()))

    def test_s9_b10_bulk_config_validation_and_refusals(self) -> None:
        """Bulk configuration loading rejects invalid types, statuses, and limit values."""
        base_text = (bulk_fixture_root() / "mixed_corpus" / "bulk.toml").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Path(tmpdir) / "bulk.toml"
            for old, new, expected_msg in (
                ('source_type = "local.directory"', 'source_type = "network.remote"', "unsupported source_type"),
                ('corpus_kind = "mixed_corpus"', 'corpus_kind = "unknown_kind"', "unsupported corpus_kind"),
                ('policy_status = "allowed_with_limits"', 'policy_status = "blocked"', "source policy status is not allowed"),
                ('max_files = 100', 'max_files = 0', "must be a positive integer"),
                ('max_depth = 8', 'max_depth = -1', "must be a positive integer"),
            ):
                cfg.write_text(base_text.replace(old, new), encoding="utf-8")
                with self.subTest(modification=new):
                    with self.assertRaises(BulkPolicyError) as cm_bulk:
                        load_bulk_source_config(cfg)
                    self.assertIn(expected_msg, str(cm_bulk.exception))

            cfg.write_text("not a valid toml = [", encoding="utf-8")
            with self.assertRaises(BulkPolicyError) as cm_toml:
                load_bulk_source_config(cfg)
            self.assertIn("invalid bulk config", str(cm_toml.exception))

    def test_s9_b11_feed_config_url_method_and_policy_gating(self) -> None:
        """Feed configuration validates URL scheme, credentials, HTTP method, and policy status."""
        base_text = source_fixture("allowed-rss.toml").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Path(tmpdir) / "feed.toml"
            for old, new, expected_msg in (
                (
                    'url = "https://example.invalid/rss.xml"',
                    'url = "https://user:pass@example.invalid/rss.xml"',
                    "acquisition.url must not contain credentials",
                ),
                (
                    'url = "https://example.invalid/rss.xml"',
                    'url = "ftp://example.invalid/rss.xml"',
                    "acquisition.url must use http or https",
                ),
                ('method = "GET"', 'method = "POST"', "feed acquisition method must be GET"),
                ('status = "allowed_with_limits"', 'status = "blocked_login_required"', "source policy status blocks ingestion"),
                ('requires_manual_review = false', 'requires_manual_review = true', "source requires manual review before acquisition"),
            ):
                cfg.write_text(base_text.replace(old, new), encoding="utf-8")
                with self.subTest(modification=new):
                    with self.assertRaises(SourcePolicyError) as cm_feed:
                        load_feed_source_config(cfg)
                    self.assertIn(expected_msg, str(cm_feed.exception))

    def test_s9_b12_feed_item_limits_and_disallowed_flags(self) -> None:
        """Feed configuration rejects anti-bot bypass flags, nonpositive limits, and malformed IDs."""
        base_text = source_fixture("allowed-rss.toml").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Path(tmpdir) / "feed.toml"
            for extra in (
                "login_required = true",
                "requires_captcha = true",
                "anti_bot_bypass = true",
            ):
                cfg.write_text(base_text + f"\n[source.flags]\n{extra}\n", encoding="utf-8")
                with self.subTest(flag=extra):
                    with self.assertRaises(SourcePolicyError) as cm_flag:
                        load_feed_source_config(cfg)
                    self.assertIn("is not allowed for feed ingestion", str(cm_flag.exception))

            for old, new, expected_msg in (
                ('timeout_seconds = 10', 'timeout_seconds = 0', "must be a positive integer"),
                ('max_artifact_bytes = 1048576', 'max_artifact_bytes = -1', "must be a positive integer"),
                ('id = "example-rss-feed"', 'id = "bad:id:with:colons"', "source id must be an explicit safe identifier"),
                ('type = "feed.rss"', 'type = "feed.unsupported"', "source type must be feed.rss, feed.atom, or feed.json"),
            ):
                cfg.write_text(base_text.replace(old, new), encoding="utf-8")
                with self.subTest(modification=new):
                    with self.assertRaises(SourcePolicyError) as cm_lim:
                        load_feed_source_config(cfg)
                    self.assertIn(expected_msg, str(cm_lim.exception))

    def test_s9_b13_warc_multiline_headers_and_http_message_parsing(self) -> None:
        """WARC parsing handles continuation headers, HTTP message splitting, and malformed frames."""
        lines = [
            "Host: example.com",
            "User-Agent: test-agent",
            " continuation line",
            "Content-Type: text/html",
        ]
        headers = _parse_header_lines(lines)
        self.assertEqual(headers["user-agent"], "test-agent continuation line")
        self.assertEqual(headers["content-type"], "text/html")

        valid_http = b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<html>test</html>"
        msg_headers, body = _parse_http_message_payload(valid_http, response=True)
        self.assertEqual(msg_headers.get("content-type"), "text/html")
        self.assertEqual(body, b"<html>test</html>")

        invalid_http = b"INVALID /page HTTP/1.1\r\n\r\nbody"
        msg_headers, body = _parse_http_message_payload(invalid_http, response=True)
        self.assertEqual(msg_headers, {})
        self.assertEqual(body, b"")

        truncated_warc = b"WARC/1.1\r\nContent-Length: 100\r\n\r\nshort"
        result = _next_warc_record(truncated_warc, 0)
        self.assertIsInstance(result, str)
        self.assertIn("truncated payload", str(result))

        bad_version = b"WARC/0.9\r\nContent-Length: 5\r\n\r\nhello"
        result = _next_warc_record(bad_version, 0)
        self.assertIsInstance(result, str)
        self.assertIn("unsupported WARC version", str(result))

    def test_s9_b14_warc_uri_redaction_and_target_keys(self) -> None:
        """WARC target processing redacts sensitive credentials and query parameters."""
        uri = "https://alice:secret123@example.com/repo/page?token=xyz123&public=1"
        summary, key, redacted = _warc_target(uri)
        self.assertTrue(redacted)
        self.assertIsNotNone(summary)
        self.assertIsNotNone(key)
        self.assertNotIn("secret123", str(summary))
        self.assertIn("token=<redacted>", str(summary))
        self.assertIn("public=1", str(summary))

        raw_headers = {
            "authorization": "Bearer secret_token",
            "cookie": "session=xyz",
            "warc-type": "response",
            "content-type": "text/html",
        }
        safe = _safe_warc_headers(raw_headers)
        self.assertEqual(safe.get("authorization"), "<redacted>")
        self.assertEqual(safe.get("cookie"), "<redacted>")
        self.assertEqual(safe.get("warc-type"), "response")
        self.assertEqual(safe.get("content-type"), "text/html")

        self.assertEqual(_warc_payload_route("text/html"), "html")
        self.assertEqual(_warc_payload_route("application/feed+json"), "json")
        self.assertEqual(_warc_payload_route("application/rss+xml"), "xml")
        self.assertEqual(_warc_payload_route("text/javascript"), "javascript")
        self.assertIsNone(_warc_payload_route("application/octet-stream"))


if __name__ == "__main__":
    import sys
    sys.exit('Direct execution unsupported; use tools/run_tests.py for container sandbox admission.')
