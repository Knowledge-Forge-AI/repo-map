"""Public-safe feed and WARC wire fixtures for source-ingestion tests."""

from __future__ import annotations

import json

RSS_BODY = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Fixture Feed</title>
    <link>https://example.invalid/feed-home</link>
    <description>Local fixture only</description>
    <item>
      <guid>rss-item-1</guid>
      <title>RSS Item One</title>
      <link>https://example.invalid/items/1</link>
      <enclosure url="https://example.invalid/media/1.mp3" type="audio/mpeg" />
    </item>
  </channel>
</rss>
"""

ATOM_BODY = b"""\
<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Example Atom Fixture</title>
  <id>urn:example:atom</id>
  <updated>2026-06-30T12:00:00Z</updated>
  <entry>
    <id>urn:example:atom:1</id>
    <title>Atom Item One</title>
    <link rel="alternate" href="https://example.invalid/atom/1" />
    <updated>2026-06-30T12:30:00Z</updated>
  </entry>
</feed>
"""

JSON_FEED_BODY = json.dumps(
    {
        "version": "https://jsonfeed.org/version/1.1",
        "title": "Example JSON Fixture",
        "items": [
            {
                "id": "json-item-1",
                "title": "JSON Item One",
                "url": "https://example.invalid/json/1",
            }
        ],
    },
    sort_keys=True,
).encode("utf-8")


def warc_record(
    record_type: str,
    record_id: str,
    target_uri: str | None,
    body: bytes,
    *,
    content_type: str,
    extra_headers: dict[str, str] | None = None,
) -> bytes:
    headers = {
        "WARC-Type": record_type,
        "WARC-Record-ID": f"<{record_id}>",
        "WARC-Date": "2026-06-30T12:00:00Z",
        "Content-Type": content_type,
        "Content-Length": str(len(body)),
    }
    if target_uri is not None:
        headers["WARC-Target-URI"] = target_uri
    if extra_headers:
        headers.update(extra_headers)
    return _header_block(headers) + body + b"\r\n\r\n"

def http_response_record(
    record_type: str,
    record_id: str,
    target_uri: str,
    content_type: str,
    body: bytes,
    *,
    http_headers: dict[str, str],
) -> bytes:
    response_headers = {
        **http_headers,
        "Content-Length": str(len(body)),
    }
    http_payload = (
        b"HTTP/1.1 200 OK\r\n"
        + _http_header_lines(response_headers)
        + b"\r\n"
        + body
    )
    return warc_record(
        record_type,
        record_id,
        target_uri,
        http_payload,
        content_type="application/http; msgtype=response",
    )

def http_request_record(
    record_id: str,
    target_uri: str,
    request_headers: dict[str, str],
) -> bytes:
    http_payload = (
        b"GET /page.html HTTP/1.1\r\n"
        + _http_header_lines(request_headers)
        + b"\r\n"
    )
    return warc_record(
        "request",
        record_id,
        target_uri,
        http_payload,
        content_type="application/http; msgtype=request",
    )

def _header_block(headers: dict[str, str]) -> bytes:
    return b"WARC/1.1\r\n" + _http_header_lines(headers) + b"\r\n"

def _http_header_lines(headers: dict[str, str]) -> bytes:
    return "".join(f"{key}: {value}\r\n" for key, value in headers.items()).encode(
        "utf-8"
    )

