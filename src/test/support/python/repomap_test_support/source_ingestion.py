"""Shared support for source ingestion unit tests."""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from pathlib import Path

from repomap_kg.ops.ingestion.source import FeedFetchResponse


from repomap_test_support.source_ingestion_records import (
    RSS_BODY as RSS_BODY,
    ATOM_BODY as ATOM_BODY,
    JSON_FEED_BODY as JSON_FEED_BODY,
    warc_record as warc_record,
    http_response_record as http_response_record,
    http_request_record as http_request_record,
    _header_block as _header_block,
    _http_header_lines as _http_header_lines,
)


class SourceIngestionUnitTestCase(unittest.TestCase):
    def write_config(
        self,
        path: Path,
        *,
        source_id: str = "example-news-feed",
        source_type: str = "feed.rss",
        policy_status: str = "allowed_with_limits",
        url: str = "https://example.invalid/rss.xml",
        timeout_seconds: int | None = 10,
        max_artifact_bytes: int = 1048576,
        max_items_per_run: int | None = 100,
        secret: bool = False,
    ) -> Path:
        policy_lines = [
            f'status = "{policy_status}"',
            'preferred_method = "rss"',
            'rate_limit = "1 request per 15 minutes"',
            f"max_artifact_bytes = {max_artifact_bytes}",
            'robots_policy = "fixture"',
            'terms_policy = "fixture"',
            "requires_manual_review = false",
        ]
        if timeout_seconds is not None:
            policy_lines.append(f"timeout_seconds = {timeout_seconds}")
        if max_items_per_run is not None:
            policy_lines.append(f"max_items_per_run = {max_items_per_run}")
        secret_block = (
            '\n[credentials]\ntoken = "fixture-secret"\n' if secret else ""
        )
        path.write_text(
            "\n".join(
                [
                    "[source]",
                    f'id = "{source_id}"',
                    f'type = "{source_type}"',
                    'display_name = "Example News Feed"',
                    "",
                    "[policy]",
                    *policy_lines,
                    "",
                    "[acquisition]",
                    f'url = "{url}"',
                    'method = "GET"',
                    'user_agent = "RepoMap feed ingestion test fixture"',
                    secret_block,
                ]
            ),
            encoding="utf-8",
        )
        return path

    def write_archive_config(
        self,
        path: Path,
        *,
        source_id: str = "example-test-report",
        source_type: str = "test_report.artifact",
        policy_status: str = "allowed",
        artifact_path: str = "reports/latest",
        artifact_kind: str = "directory",
        max_artifact_bytes: int = 1048576,
        max_file_count: int = 100,
        max_depth: int = 10,
        secret: bool = False,
        extra: str = "",
    ) -> Path:
        secret_block = (
            '\n[credentials]\ntoken = "fixture-secret"\n' if secret else ""
        )
        path.write_text(
            "\n".join(
                [
                    "[source]",
                    f'id = "{source_id}"',
                    f'type = "{source_type}"',
                    'display_name = "Example Test Report"',
                    "",
                    "[policy]",
                    f'status = "{policy_status}"',
                    f"max_artifact_bytes = {max_artifact_bytes}",
                    f"max_file_count = {max_file_count}",
                    f"max_depth = {max_depth}",
                    'symlink_policy = "do_not_follow"',
                    "hidden_files = false",
                    'retention_policy = "retain-local-path-and-hash"',
                    "requires_manual_review = false",
                    "",
                    "[artifact]",
                    f'path = "{artifact_path}"',
                    f'kind = "{artifact_kind}"',
                    'profile = "test-report"',
                    'entry_document = "index.html"',
                    secret_block,
                    extra,
                ]
            ),
            encoding="utf-8",
        )
        return path

    def write_archive_artifact(self, root: Path) -> Path:
        artifact = root / "reports" / "latest"
        (artifact / "assets").mkdir(parents=True)
        (artifact / "config").mkdir()
        (artifact / "static").mkdir()
        (artifact / ".git").mkdir()
        (artifact / "index.html").write_text(
            """\
<!doctype html>
<html>
  <head>
    <title>Example Test Report</title>
    <link rel="stylesheet" href="static/report.css">
    <script src="static/app.js"></script>
  </head>
  <body>
    <header class="report-header">
      <h1 id="summary">Example Test Report</h1>
      <span class="status-badge status-passed">Passed</span>
    </header>
    <img src="assets/logo.svg" alt="logo">
    <a href="https://example.invalid/report">External</a>
    <a href="javascript:alert('nope')">No execution</a>
  </body>
</html>
""",
            encoding="utf-8",
        )
        (artifact / "static" / "report.css").write_text(
            """\
.report-header { color: #f8fafc; }
.status-badge.status-passed { background: #16a34a; }
.hero { background-image: url("../assets/logo.svg"); }
""",
            encoding="utf-8",
        )
        (artifact / "static" / "app.js").write_text(
            """\
import { renderChunk } from "./chunk.js";
export function renderReport() {
  return renderChunk("summary");
}
const apiToken = "fixture-secret";
fetch("https://example.invalid/report-data.json");
//# sourceMappingURL=app.js.map
""",
            encoding="utf-8",
        )
        (artifact / "static" / "chunk.js").write_text(
            "export function renderChunk(name) { return name; }\n",
            encoding="utf-8",
        )
        (artifact / "static" / "app.js.map").write_text(
            '{"version": 3, "sources": ["app.ts"]}\n',
            encoding="utf-8",
        )
        (artifact / "config" / "settings.json").write_text(
            json.dumps(
                {
                    "report": {"entry": "../index.html"},
                    "credentials": {"token": "fixture-secret"},
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        (artifact / "assets" / "logo.svg").write_text(
            "<svg><title>logo</title></svg>\n",
            encoding="utf-8",
        )
        (artifact / ".hidden-secret").write_text("fixture-secret\n", encoding="utf-8")
        (artifact / ".git" / "config").write_text("[core]\n", encoding="utf-8")
        return artifact

    def write_warc_config(
        self,
        path: Path,
        *,
        source_id: str = "example-warc-archive",
        source_type: str = "saved_page.archive",
        policy_status: str = "allowed",
        artifact_path: str = "warc_artifacts/example.warc",
        artifact_kind: str = "warc",
        max_artifact_bytes: int = 1048576,
        max_file_count: int = 10,
        max_warc_records: int | None = 100,
        max_record_bytes: int | None = 1048576,
        max_total_payload_bytes: int | None = 1048576,
        secret: bool = False,
        extra: str = "",
    ) -> Path:
        policy_lines = [
            f'status = "{policy_status}"',
            f"max_artifact_bytes = {max_artifact_bytes}",
            f"max_file_count = {max_file_count}",
            'retention_policy = "materialize-safe-payloads"',
            "requires_manual_review = false",
        ]
        if max_warc_records is not None:
            policy_lines.append(f"max_warc_records = {max_warc_records}")
        if max_record_bytes is not None:
            policy_lines.append(f"max_record_bytes = {max_record_bytes}")
        if max_total_payload_bytes is not None:
            policy_lines.append(
                f"max_total_payload_bytes = {max_total_payload_bytes}"
            )
        secret_block = (
            '\n[credentials]\ntoken = "fixture-secret"\n' if secret else ""
        )
        path.write_text(
            "\n".join(
                [
                    "[source]",
                    f'id = "{source_id}"',
                    f'type = "{source_type}"',
                    'display_name = "Example WARC Archive"',
                    "",
                    "[policy]",
                    *policy_lines,
                    "",
                    "[artifact]",
                    f'path = "{artifact_path}"',
                    f'kind = "{artifact_kind}"',
                    'profile = "warc-local-archive"',
                    secret_block,
                    extra,
                ]
            ),
            encoding="utf-8",
        )
        return path

    def write_warc_fixture(self, root: Path) -> Path:
        artifact_dir = root / "warc_artifacts"
        artifact_dir.mkdir()
        warc_path = artifact_dir / "example.warc"
        records = [
            warc_record(
                "warcinfo",
                "urn:uuid:warcinfo",
                None,
                b"software: RepoMap fixture\n",
                content_type="application/warc-fields",
            ),
            http_response_record(
                "response",
                "urn:uuid:html-1",
                "https://user:fixture-secret@example.invalid/page.html?token=fixture-secret&ok=1",
                "text/html",
                b"<!doctype html><html><head><title>Archived</title><link rel=\"stylesheet\" href=\"style.css\"></head><body><h1 id=\"top\">Archived</h1></body></html>",
                http_headers={
                    "Set-Cookie": "session=fixture-secret",
                    "Content-Type": "text/html",
                },
            ),
            warc_record(
                "resource",
                "urn:uuid:css-1",
                "https://example.invalid/style.css",
                b".archived { color: #fff; }\n",
                content_type="text/css",
            ),
            warc_record(
                "resource",
                "urn:uuid:json-1",
                "https://example.invalid/config.json",
                b'{"command": "python3", "credentials": {"token": "fixture-secret"}}',
                content_type="application/json",
            ),
            http_response_record(
                "response",
                "urn:uuid:js-1",
                "https://example.invalid/assets/app.js",
                "text/javascript",
                (
                    b"export function archivedReport() { return 'ok'; }\n"
                    b"const apiToken = 'fixture-secret';\n"
                    b"//# sourceMappingURL=payload.js.map\n"
                ),
                http_headers={"Content-Type": "text/javascript"},
            ),
            http_request_record(
                "urn:uuid:request-1",
                "https://example.invalid/page.html",
                {"Authorization": "Bearer fixture-secret", "Cookie": "a=fixture-secret"},
            ),
            warc_record(
                "revisit",
                "urn:uuid:revisit-1",
                "https://example.invalid/page.html",
                b"",
                content_type="application/warc-fields",
                extra_headers={"WARC-Refers-To": "<urn:uuid:html-1>"},
            ),
            warc_record(
                "metadata",
                "urn:uuid:html-1",
                "https://example.invalid/page.html",
                b"duplicate id metadata\n",
                content_type="text/plain",
            ),
        ]
        warc_path.write_bytes(b"".join(records))
        return warc_path

    def fetcher_returning(
        self,
        body: bytes,
        *,
        status: int = 200,
        calls: list[str] | None = None,
    ):
        def fetcher(config):
            if calls is not None:
                calls.append(config.url)
            return FeedFetchResponse(
                status=status,
                headers={"content-type": "application/xml"},
                body=body,
            )

        return fetcher

    def fake_loader(self, _psql_args, observations, **_kwargs):
        from repomap_kg.storage import LoadSummary

        self.assertGreater(len(observations), 0)
        return LoadSummary(repository_id=7, run_id=11, files=1)

    @staticmethod
    def fixed_clock():
        return datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC)


class FakeOpener:
    def __init__(self, response_or_error):
        self.response_or_error = response_or_error
        self.request = None
        self.timeout = None

    def open(self, request, *, timeout):
        self.request = request
        self.timeout = timeout
        if isinstance(self.response_or_error, Exception):
            raise self.response_or_error
        return self.response_or_error

class FakeResponse:
    def __init__(self, status, body, headers):
        self.status = status
        self._body = body
        self.headers = headers

    def getcode(self):
        return self.status

    def read(self, _limit):
        return self._body

class FakeBody:
    def __init__(self, body):
        self.body = body

    def read(self, _limit):
        return self.body

    def close(self):
        return None
