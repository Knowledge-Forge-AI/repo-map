"""Support helpers for static feed extraction."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree

from repomap_kg.graph.keys import (
    dynamic_key,
    external_key,
    external_url_key,
    file_key,
    unknown_key,
)


SAFE_SUMMARY_LIMIT = 160

TAG_PATTERN = re.compile(r"<[^>]+>")
SCRIPT_STYLE_PATTERN = re.compile(
    r"<\s*(script|style)\b.*?<\s*/\s*\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
WHITESPACE_PATTERN = re.compile(r"\s+")
DYNAMIC_REFERENCE_PATTERN = re.compile(r"(\$[A-Za-z_][A-Za-z0-9_]*|\$\{|{{|}}|[*?])")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

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
)


def _item_identity(
    *candidates: tuple[str, str | None],
    ordinal: int,
) -> tuple[str, str, str]:
    for source, value in candidates:
        if value:
            strength = "weak" if source.startswith("title+") else "strong"
            return f"{source}:{value}", source, strength
    return f"ordinal:{ordinal}", "structural-ordinal", "structural"


def _title_date_identity(title: str | None, date_text: str | None) -> str | None:
    if not title or not date_text:
        return None
    normalized = _parse_date(date_text) or _collapse_text(date_text)
    return f"{_slug(title)}:{normalized}"


def _reference_target(relative_path: str, raw_target: str) -> str:
    value = raw_target.strip()
    if not value:
        return unknown_key("feed.reference", "missing-target")
    if DYNAMIC_REFERENCE_PATTERN.search(value) or value.startswith("~"):
        return dynamic_key("file", "feed-reference-expanded-from-variable")
    parsed = urlsplit(value)
    if parsed.scheme:
        scheme = parsed.scheme.lower()
        if scheme in ("http", "https"):
            if parsed.netloc:
                return external_url_key(value)
            return unknown_key("external.url", "malformed-feed-reference")
        if scheme == "mailto":
            return external_url_key(value)
        return dynamic_key("url", "unsupported-url-scheme")
    if value.startswith("/"):
        return external_key("file", "absolute-feed-reference")
    source_parent = PurePosixPath(relative_path).parent
    target_path = (source_parent / value).as_posix()
    try:
        return file_key(target_path)
    except Exception:
        return unknown_key("file", "repo-escaping-feed-reference")


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_summary(value: str | None) -> str | None:
    if value is None:
        return None
    if _contains_secret_marker(value):
        return None
    text = _collapse_text(_strip_html(value))
    if not text:
        return None
    if len(text) > SAFE_SUMMARY_LIMIT:
        return text[: SAFE_SUMMARY_LIMIT - 1].rstrip() + "..."
    return text


def _safe_label(value: str | None) -> str | None:
    summary = _safe_summary(value)
    if summary is None:
        return None
    return summary


def _strip_html(value: str) -> str:
    without_script = SCRIPT_STYLE_PATTERN.sub(" ", value)
    return TAG_PATTERN.sub(" ", without_script)


def _collapse_text(value: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", value).strip()


def _contains_secret_marker(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in SECRET_MARKERS)


def _slug(value: str) -> str:
    text = _collapse_text(_strip_html(value)).lower()
    parts = []
    previous_dash = False
    for character in text:
        if character.isalnum():
            parts.append(character)
            previous_dash = False
        elif not previous_dash:
            parts.append("-")
            previous_dash = True
    slug = "".join(parts).strip("-")
    return slug or "untitled"


def _rss_author(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    text = _collapse_text(value)
    match = re.search(r"\(([^)]+)\)", text)
    name = match.group(1) if match else text
    if EMAIL_PATTERN.match(name):
        return {"name": "redacted-author", "email_redacted": True}
    if "@" in text:
        return {"name": _safe_label(name), "email_redacted": True}
    return {"name": _safe_label(name)}


def _atom_link(parent: ElementTree.Element, rel: str) -> str | None:
    fallback = None
    for link in _children(parent, "link"):
        href = link.attrib.get("href", "").strip()
        if not href:
            continue
        link_rel = link.attrib.get("rel", "alternate")
        if link_rel == rel:
            return href
        if link_rel == "alternate":
            fallback = href
    if rel == "alternate":
        return fallback
    return None


def _text_value(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _first_child(parent: ElementTree.Element, name: str) -> ElementTree.Element | None:
    for child in parent:
        if _local_name(child.tag) == name:
            return child
    return None


def _children(parent: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    return [child for child in parent if _local_name(child.tag) == name]


def _child_text(parent: ElementTree.Element, name: str) -> str | None:
    child = _first_child(parent, name)
    if child is None:
        return None
    return _element_text(child)


def _element_text(element: ElementTree.Element) -> str | None:
    text = "".join(element.itertext())
    text = _collapse_text(text)
    return text or None


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    if ":" in tag:
        return tag.rsplit(":", 1)[1]
    return tag
