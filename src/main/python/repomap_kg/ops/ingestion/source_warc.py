"""WARC parsing, target, and header helpers for source ingestion."""

from __future__ import annotations

import hashlib
import urllib.parse
from collections.abc import Mapping, Sequence
from typing import Any

from repomap_kg.graph.keys import (
    dynamic_key,
    external_key,
    external_url_key,
    file_key,
    unknown_key,
)
from repomap_kg.ops.ingestion.source_common import SECRET_MARKERS


JAVASCRIPT_WARC_MEDIA_TYPES = frozenset(
    {
        "text/javascript",
        "application/javascript",
        "application/x-javascript",
        "text/ecmascript",
        "application/ecmascript",
        "text/typescript",
        "application/typescript",
    }
)
SAFE_WARC_HEADER_NAMES = frozenset(
    {
        "content-length",
        "content-type",
        "etag",
        "last-modified",
        "warc-block-digest",
        "warc-concurrent-to",
        "warc-date",
        "warc-payload-digest",
        "warc-record-id",
        "warc-refers-to",
        "warc-target-uri",
        "warc-type",
    }
)
SENSITIVE_HEADER_NAMES = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "proxy-authorization",
        "x-api-key",
        "api-key",
    }
)


def _next_warc_record(
    data: bytes,
    offset: int,
) -> tuple[int, str, dict[str, str], bytes, bytes] | str:
    crlf_header_end = data.find(b"\r\n\r\n", offset)
    lf_header_end = data.find(b"\n\n", offset)
    candidates = [
        (position, 4)
        for position in (crlf_header_end,)
        if position >= 0
    ] + [
        (position, 2)
        for position in (lf_header_end,)
        if position >= 0
    ]
    if not candidates:
        return f"malformed WARC record at byte {offset}: missing header terminator"
    header_end, separator_length = min(candidates, key=lambda item: item[0])
    raw_header_bytes = data[offset:header_end]
    header_text = raw_header_bytes.decode("utf-8", errors="replace")
    lines = header_text.splitlines()
    if not lines or lines[0] not in {"WARC/1.0", "WARC/1.1"}:
        return f"malformed WARC record at byte {offset}: unsupported WARC version"
    headers = _parse_header_lines(lines[1:])
    content_length_text = headers.get("content-length")
    if content_length_text is None:
        return f"malformed WARC record at byte {offset}: missing Content-Length"
    try:
        content_length = int(content_length_text)
    except ValueError:
        return f"malformed WARC record at byte {offset}: invalid Content-Length"
    if content_length < 0:
        return f"malformed WARC record at byte {offset}: negative Content-Length"
    payload_start = header_end + separator_length
    payload_end = payload_start + content_length
    if payload_end > len(data):
        return f"malformed WARC record at byte {offset}: truncated payload"
    next_offset = payload_end
    if data[next_offset : next_offset + 2] == b"\r\n":
        next_offset += 2
    elif data[next_offset : next_offset + 1] == b"\n":
        next_offset += 1
    return next_offset, lines[0], headers, raw_header_bytes, data[payload_start:payload_end]


def _parse_header_lines(lines: Sequence[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    current_key: str | None = None
    for line in lines:
        if not line:
            continue
        if line[:1] in {" ", "\t"} and current_key is not None:
            headers[current_key] = f"{headers[current_key]} {line.strip()}"
            continue
        key, separator, value = line.partition(":")
        if not separator:
            continue
        current_key = key.strip().lower()
        headers[current_key] = value.strip()
    return headers


def _warc_record_identity(
    *,
    headers: Mapping[str, str],
    record_type: str,
    target_uri_summary: str | None,
    ordinal: int,
) -> tuple[str, str, str]:
    record_id = _normalise_warc_record_id(headers.get("warc-record-id"))
    if record_id:
        return record_id, "warc_record_id", "strong"
    warc_date = headers.get("warc-date")
    if warc_date and target_uri_summary:
        digest = hashlib.sha256(
            f"{warc_date}\0{target_uri_summary}\0{record_type}".encode("utf-8")
        ).hexdigest()[:16]
        return f"date-target-type:{digest}", "warc-date-target-uri-type", "fallback"
    return f"ordinal:{ordinal:04d}", "record-ordinal", "structural"


def _normalise_warc_record_id(record_id: str | None) -> str:
    if not record_id:
        return ""
    return f"record:{record_id.strip()}"


def _parse_http_message_payload(
    block: bytes,
    *,
    response: bool,
) -> tuple[dict[str, str], bytes]:
    delimiter = b"\r\n\r\n"
    separator_length = 4
    header_end = block.find(delimiter)
    if header_end < 0:
        delimiter = b"\n\n"
        separator_length = 2
        header_end = block.find(delimiter)
    if header_end < 0:
        return {}, b""
    header_text = block[:header_end].decode("utf-8", errors="replace")
    lines = header_text.splitlines()
    if not lines:
        return {}, b""
    if response and not lines[0].upper().startswith("HTTP/"):
        return {}, b""
    return (
        _parse_header_lines(lines[1:]),
        block[header_end + separator_length :],
    )


def _http_content_type(headers: Mapping[str, str]) -> str | None:
    return headers.get("content-type")


def _warc_payload_route(content_type: str | None) -> str | None:
    if content_type is None:
        return None
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type in {"text/html", "application/xhtml+xml"}:
        return "html"
    if media_type == "text/css":
        return "css"
    if media_type in {
        "application/json",
        "application/feed+json",
        "application/jsonfeed+json",
    }:
        return "json"
    if media_type in {
        "application/xml",
        "text/xml",
        "application/rss+xml",
        "application/atom+xml",
    }:
        return "xml"
    if media_type in JAVASCRIPT_WARC_MEDIA_TYPES:
        return "javascript"
    return None


def _warc_payload_extension(extractor_route: str) -> str:
    if extractor_route == "html":
        return ".html"
    if extractor_route == "css":
        return ".css"
    if extractor_route == "json":
        return ".json"
    if extractor_route == "xml":
        return ".xml"
    if extractor_route == "javascript":
        return ".js"
    return ".bin"


def _safe_warc_headers(headers: Mapping[str, str]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in sorted(headers.items()):
        key_lower = key.lower()
        if key_lower == "warc-target-uri":
            safe[key_lower] = _warc_target(value)[0]
            continue
        if _is_sensitive_header_name(key_lower):
            safe[key_lower] = "<redacted>"
            continue
        if key_lower in SAFE_WARC_HEADER_NAMES:
            safe[key_lower] = _redact_header_value(key_lower, value)
    return safe


def _is_sensitive_header_name(name: str) -> bool:
    name_lower = name.lower()
    return name_lower in SENSITIVE_HEADER_NAMES or _is_secret_marker(name_lower)


def _redact_header_value(key: str, value: str) -> str:
    if _is_secret_marker(key) or _is_secret_marker(value):
        return "<redacted>"
    return value


def _warc_target(uri: str | None) -> tuple[str | None, str | None, bool]:
    if not uri:
        return None, None, False
    summary, redacted = _redact_warc_target_uri(uri)
    return summary, _warc_target_key(summary), redacted


def _redact_warc_target_uri(uri: str) -> tuple[str, bool]:
    parsed = urllib.parse.urlsplit(uri)
    redacted = False
    if parsed.username or parsed.password:
        redacted = True
    netloc = parsed.hostname or parsed.netloc
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    query_items = urllib.parse.parse_qsl(
        parsed.query,
        keep_blank_values=True,
        strict_parsing=False,
    )
    sanitized_items: list[tuple[str, str]] = []
    for key, value in query_items:
        if _is_secret_marker(key) or _is_secret_marker(value):
            sanitized_items.append((key, "<redacted>"))
            redacted = True
        else:
            sanitized_items.append((key, value))
    query = "&".join(
        f"{urllib.parse.quote(key, safe='')}="
        f"{value if value == '<redacted>' else urllib.parse.quote(value, safe='')}"
        for key, value in sanitized_items
    )
    fragment = "" if _is_secret_marker(parsed.fragment) else parsed.fragment
    if fragment != parsed.fragment:
        redacted = True
    return (
        urllib.parse.urlunsplit(
            (parsed.scheme, netloc, parsed.path, query, fragment)
        ),
        redacted,
    )


def _warc_target_key(uri_summary: str | None) -> str | None:
    if not uri_summary:
        return None
    parsed = urllib.parse.urlsplit(uri_summary)
    scheme = parsed.scheme.lower()
    if scheme in {"http", "https", "mailto"}:
        return external_url_key(uri_summary)
    if scheme == "javascript":
        return dynamic_key("warc.target-uri", "javascript")
    if "$" in uri_summary or "{" in uri_summary or "}" in uri_summary:
        return dynamic_key("warc.target-uri", "template")
    if scheme == "file" or uri_summary.startswith("/"):
        return external_key("file", "absolute-warc-reference")
    if not scheme and uri_summary and not uri_summary.startswith("../"):
        return file_key(uri_summary)
    return unknown_key("warc.target-uri", "unsupported-scheme")


def _is_secret_marker(value: str) -> bool:
    normalized = value.lower()
    return any(marker in normalized for marker in SECRET_MARKERS)
