import unittest
from pathlib import Path
from typing import Mapping


from repomap_kg.ops.ingestion import source


class SourceIngestionHelperBranchUnitTests(unittest.TestCase):
    def test_source_ingestion_validation_helpers_cover_safe_error_branches(self):
        self.assertEqual(source._mapping({"source": {"id": "x"}}, "source"), {"id": "x"})
        with self.assertRaises(source.SourcePolicyError):
            source._mapping({"source": []}, "source")

        self.assertEqual(source._required_text({"id": " source "}, "id", "id"), "source")
        payload: Mapping[str, object]
        for payload in ({}, {"id": ""}, {"id": 7}):
            with self.subTest(payload=payload):
                with self.assertRaises(source.SourcePolicyError):
                    source._required_text(payload, "id", "id")
        self.assertIsNone(source._optional_text({}, "id"))
        self.assertEqual(source._optional_text({"id": " value "}, "id"), "value")
        self.assertIsNone(source._optional_text({"id": "   "}, "id"))
        with self.assertRaises(source.SourcePolicyError):
            source._optional_text({"id": 7}, "id")

        self.assertEqual(source._required_positive_int({"limit": 1}, "limit", "limit"), 1)
        for payload in ({}, {"limit": True}, {"limit": 0}):
            with self.subTest(payload=payload):
                with self.assertRaises(source.SourcePolicyError):
                    source._required_positive_int(payload, "limit", "limit")
        self.assertEqual(source._positive_int_or_default(None, "limit", default=3), 3)
        with self.assertRaises(source.SourcePolicyError):
            source._positive_int_or_default(None, "limit", default=None)
        for value in (False, -1):
            with self.subTest(value=value):
                with self.assertRaises(source.SourcePolicyError):
                    source._positive_int_or_default(value, "limit", default=3)

        self.assertTrue(source._required_bool({"flag": True}, "flag", "flag"))
        with self.assertRaises(source.SourcePolicyError):
            source._required_bool({}, "flag", "flag")
        self.assertFalse(source._optional_bool(None, "flag", default=False))
        with self.assertRaises(source.SourcePolicyError):
            source._optional_bool("true", "flag", default=False)

        source._validate_source_id("safe-id")
        for source_id in ("https://example.invalid/feed", "bad id"):
            with self.subTest(source_id=source_id):
                with self.assertRaises(source.SourcePolicyError):
                    source._validate_source_id(source_id)
        source._validate_source_type("feed.rss")
        with self.assertRaises(source.SourcePolicyError):
            source._validate_source_type("unknown")
        source._validate_archive_source_type("local.file")
        with self.assertRaises(source.SourcePolicyError):
            source._validate_archive_source_type("feed.rss")
        source._validate_warc_source_type("saved_page.archive")
        with self.assertRaises(source.SourcePolicyError):
            source._validate_warc_source_type("feed.rss")
        source._validate_policy_status("allowed")
        with self.assertRaises(source.SourcePolicyError):
            source._validate_policy_status("blocked_terms_risk")
        with self.assertRaises(source.SourcePolicyError):
            source._validate_policy_status("unknown")

        source._validate_url("https://example.invalid/feed")
        for url in ("ftp://example.invalid/feed", "https:///feed", "https://u:p@example.invalid/feed"):
            with self.subTest(url=url):
                with self.assertRaises(source.SourcePolicyError):
                    source._validate_url(url)
        source._validate_method("get")
        with self.assertRaises(source.SourcePolicyError):
            source._validate_method("POST")
        source._validate_local_artifact_path("archive.zip")
        for path in ("https://example.invalid/archive.zip", "//server/archive.zip"):
            with self.subTest(path=path):
                with self.assertRaises(source.SourcePolicyError):
                    source._validate_local_artifact_path(path)

        source._reject_archive_network_fields({"artifact": {"path": "archive.zip"}})
        for payload in (
            {"acquisition": {"url": "https://example.invalid/archive.zip"}},
            {"artifact": {"url": "archive.zip"}},
            {"artifact": {"path": "https://example.invalid/archive.zip"}},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(source.SourcePolicyError):
                    source._reject_archive_network_fields(payload)

        source._validate_disallowed_flags({"policy": {"requires_login": False}})
        with self.assertRaises(source.SourcePolicyError):
            source._validate_disallowed_flags({"policy": {"requires_login": True}})
        self.assertEqual(
            source._secret_key_paths(
                {"credentials": {"api_token": "x"}, "safe": {"name": "repo"}},
            ),
            ["credentials", "credentials.api_token"],
        )
        self.assertEqual(
            source._flatten_mapping({"a": {"b": 1}, "c": 2}),
            [("a", {"b": 1}), ("a.b", 1), ("c", 2)],
        )
        self.assertEqual(source._artifact_filename("feed.json"), "feed.json")
        self.assertEqual(source._artifact_filename("feed.atom"), "atom.xml")
        self.assertEqual(source._artifact_filename("feed.rss"), "rss.xml")
        self.assertEqual(
            source._safe_url_summary("https://example.invalid/feed?token=secret#frag"),
            "https://example.invalid/feed",
        )
        self.assertEqual(
            source._content_type({"Content-Type": "application/json"}),
            "application/json",
        )
        self.assertIsNone(source._content_type({}))
        self.assertEqual(source._header_mapping({"X-Test": "1"}), {"x-test": "1"})
        self.assertEqual(source._header_mapping([]), {})

    def test_source_archive_route_and_media_type_helpers_cover_suffix_matrix(self):
        route_cases = {
            "index.html": "html",
            "style.css": "css",
            "data.json": "config-or-feed",
            "data.jsonc": "config-or-feed",
            "data.jsonl": "config-or-feed",
            "config.toml": "config-or-feed",
            "policy.plist": "config-or-feed",
            "feed.xml": "config-or-feed",
            "README.md": "markdown",
            "script.sh": "shell",
            "module.py": "python",
            "flake.nix": "nix",
            "app.tsx": "javascript",
            "image.png": "file",
        }
        for path, route in route_cases.items():
            with self.subTest(path=path):
                self.assertEqual(source._archive_extractor_route(Path(path)), route)

        media_cases = {
            "index.htm": "text/html",
            "style.css": "text/css",
            "data.json": "application/json",
            "data.jsonc": "application/jsonc",
            "events.jsonl": "application/jsonl",
            "config.toml": "application/toml",
            "policy.plist": "application/xml",
            "feed.xml": "application/xml",
            "README.markdown": "text/markdown",
            "app.mjs": "text/javascript",
            "app.cts": "text/typescript",
            "image.png": "application/octet-stream",
        }
        for path, media_type in media_cases.items():
            with self.subTest(path=path):
                self.assertEqual(source._archive_media_type(Path(path)), media_type)

    def test_source_warc_helpers_cover_target_header_and_payload_branches(self):
        target_cases = {
            None: (None, None, False),
            "": (None, None, False),
            "https://example.invalid/page?token=secret#frag": (
                "https://example.invalid/page?token=<redacted>#frag",
                True,
            ),
            "http://user:pass@example.invalid:8080/page": (
                "http://example.invalid:8080/page",
                True,
            ),
            "mailto:ops@example.invalid": ("mailto:ops@example.invalid", False),
            "javascript:alert(1)": ("javascript:alert(1)", False),
            "${dynamic}": ("${dynamic}", False),
            "file:///tmp/report.html": ("file:///tmp/report.html", False),
            "/absolute/path.html": ("/absolute/path.html", False),
            "relative/page.html": ("relative/page.html", False),
            "../parent/page.html": ("../parent/page.html", False),
            "ftp://example.invalid/file": ("ftp://example.invalid/file", False),
        }
        for uri, expected in target_cases.items():
            with self.subTest(uri=uri):
                summary, target_key, redacted = source._warc_target(uri)
                if uri in (None, ""):
                    self.assertIsNone(summary)
                    self.assertIsNone(target_key)
                    self.assertFalse(redacted)
                    continue
                expected_summary, expected_redacted = expected
                self.assertEqual(summary, expected_summary)
                self.assertEqual(redacted, expected_redacted)
                self.assertIsInstance(target_key, str)

        self.assertEqual(
            source._parse_header_lines(
                [
                    "Content-Type: text/html",
                    "\tcharset=utf-8",
                    "Malformed",
                    "",
                    "WARC-Type: response",
                ]
            ),
            {
                "content-type": "text/html charset=utf-8",
                "warc-type": "response",
            },
        )
        self.assertEqual(
            source._safe_warc_headers(
                {
                    "WARC-Type": "response",
                    "WARC-Target-URI": "https://example.invalid/?token=secret",
                    "Authorization": "Bearer secret",
                    "X-Ignored": "ignored",
                }
            ),
            {
                "authorization": "<redacted>",
                "warc-target-uri": "https://example.invalid/?token=<redacted>",
                "warc-type": "response",
            },
        )

        response_headers, response_body = source._parse_http_message_payload(
            b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<html/>",
            response=True,
        )
        self.assertEqual(response_headers["content-type"], "text/html")
        self.assertEqual(response_body, b"<html/>")
        request_headers, request_body = source._parse_http_message_payload(
            b"GET / HTTP/1.1\nHost: example.invalid\n\nbody",
            response=False,
        )
        self.assertEqual(request_headers["host"], "example.invalid")
        self.assertEqual(request_body, b"body")
        self.assertEqual(
            source._parse_http_message_payload(b"no headers", response=True),
            ({}, b""),
        )
        self.assertEqual(
            source._parse_http_message_payload(
                b"GET / HTTP/1.1\r\nHost: example.invalid\r\n\r\nbody",
                response=True,
            ),
            ({}, b""),
        )
