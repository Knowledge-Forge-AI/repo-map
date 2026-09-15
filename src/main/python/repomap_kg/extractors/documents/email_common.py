"""Shared context, observation, and redaction helpers for email extraction."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from repomap_kg import __version__
from repomap_kg.observations.raw import RawObservation


EXTRACTOR = "repo-email"
PARSER = "stdlib-email"
MAX_MIME_PARTS = 200
SECRET_MARKERS = (
    "token",
    "secret",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "credential",
    "private_key",
    "access_key",
    "refresh_token",
    "bearer",
    "auth",
    "client_secret",
    "secret_key",
    "access_token",
    "id_token",
    "session",
    "cookie",
    "connection_string",
    "jdbc_url",
    "datasource_password",
    "one_time_code",
    "verification_code",
    "reset_code",
    "reset_link",
    "magic_link",
    "unsubscribe_token",
    "tracking_pixel",
    "auth_link",
    "invoice_number",
    "account_number",
    "ssn",
    "tax_id",
    "dob",
    "phone",
    "address",
    "medical",
    "prescription",
    "bank",
    "routing",
    "credit_card",
    "card_number",
)


@dataclass(frozen=True)
class _MessageContext:
    relative_path: str
    source_id_prefix: str
    metadata_format: str
    message_parent_key: str | None = None
    mailbox_file_key: str | None = None
    mbox_message_ordinal: int | None = None


def _urls_in_header(value: str) -> list[str]:
    return re.findall(r"https?://[^<>,\s]+|mailto:[^<>,\s]+", value or "")


def _redact_url_text(value: str) -> str:
    result = value
    for url in _urls_in_header(value):
        result = result.replace(url, _redact_url(url))
    return result


def _redact_url(url: str) -> str:
    parsed = urlsplit(url)
    query = _redacted_query(parsed.query)
    if parsed.scheme.lower() == "mailto":
        domain = "example.invalid"
        if "@" in parsed.path:
            candidate = parsed.path.rsplit("@", 1)[1].lower()
            if candidate and not _is_secret_prone(candidate):
                domain = candidate
        return urlunsplit((parsed.scheme, "", f"redacted@{domain}", query, ""))
    netloc = parsed.hostname or ""
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, query, ""))


def _redacted_query(raw_query: str) -> str:
    query = []
    for key, value in parse_qsl(raw_query, keep_blank_values=True):
        if _is_secret_prone(key) or _is_secret_prone(value):
            query.append((key, "REDACTED"))
        else:
            query.append((key, value))
    return urlencode(query, doseq=True)


def _redacted_filename(filename: str | None) -> str | None:
    if not filename:
        return None
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix and len(suffix) <= 16 and re.fullmatch(r"\.[a-z0-9]+", suffix):
        return f"<redacted>{suffix}"
    return "<redacted>"


def _parsed_date(value: str | None) -> tuple[str | None, str]:
    if not isinstance(value, str) or not value.strip():
        return None, "missing"
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None, "invalid"
    return parsed.isoformat(), "valid"


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _is_secret_prone(value: str | None) -> bool:
    if not isinstance(value, str):
        return False
    normalized = re.sub(r"[^a-z0-9]+", "", value.lower())
    return any(marker.replace("_", "") in normalized for marker in SECRET_MARKERS)


def _header_slug(header_name: str) -> str:
    return header_name.lower().replace("-", "_")


def _observation(
    *,
    kind: str,
    relative_path: str,
    source_id: str,
    metadata: dict[str, Any],
    confidence: str = "extracted",
    name: str | None = None,
    target: str | None = None,
) -> RawObservation:
    return RawObservation(
        kind=kind,
        source_id=source_id,
        path=relative_path,
        confidence=confidence,
        extractor=EXTRACTOR,
        extractor_version=__version__,
        name=name,
        target=target,
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def _parse_error(
    context: _MessageContext,
    error_kind: str,
    message_summary: str,
    *,
    recovered: bool,
) -> RawObservation:
    return _observation(
        kind="email.parse_error",
        relative_path=context.relative_path,
        source_id=f"{context.source_id_prefix}#email-parse-error:{error_kind}",
        confidence="unknown",
        metadata={
            "format": context.metadata_format,
            "parser": PARSER,
            "error_kind": error_kind,
            "message_summary": message_summary,
            "recovered": recovered,
            "mailbox_file_key": context.mailbox_file_key,
            "mbox_message_ordinal": context.mbox_message_ordinal,
        },
    )
