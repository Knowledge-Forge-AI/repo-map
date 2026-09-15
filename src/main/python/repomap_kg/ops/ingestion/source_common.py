"""Shared source ingestion policy and config helpers."""

from __future__ import annotations

import json
import re
import urllib.parse
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any


FEED_SOURCE_TYPES = frozenset({"feed.rss", "feed.atom", "feed.json"})
ARCHIVE_SOURCE_TYPES = frozenset(
    {
        "saved_page.archive",
        "test_report.artifact",
        "fixture.corpus",
        "manual.import",
        "static_artifact",
        "local.directory",
        "local.file",
    }
)
WARC_SOURCE_TYPES = ARCHIVE_SOURCE_TYPES

ALLOWED_POLICY_STATUSES = frozenset({"allowed", "allowed_with_limits"})
BLOCKED_POLICY_STATUSES = frozenset(
    {
        "manual_review_required",
        "blocked_login_required",
        "blocked_anti_bot_circumvention",
        "blocked_terms_risk",
        "blocked_privacy_risk",
        "blocked_circumvention_required",
        "blocked_unknown",
    }
)
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

DISALLOWED_TRUE_FLAGS = (
    "requires_login",
    "login_required",
    "requires_captcha",
    "captcha_required",
    "uses_proxy_rotation",
    "proxy_rotation",
    "requires_browser",
    "browser_automation",
    "circumvention_required",
    "anti_bot_bypass",
    "stealth",
)
SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class SourcePolicyError(ValueError):
    """Raised when a source definition is not policy-approved."""


def json_dumps_stable(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise SourcePolicyError(f"{key} table is required")
    return value


def _required_text(payload: Mapping[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SourcePolicyError(f"{label} is required")
    return value.strip()


def _optional_text(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise SourcePolicyError(f"{key} must be a string")
    value = value.strip()
    return value or None


def _required_positive_int(
    payload: Mapping[str, Any],
    key: str,
    label: str,
) -> int:
    if key not in payload:
        raise SourcePolicyError(f"{label} is required")
    value = payload[key]
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise SourcePolicyError(f"{label} must be a positive integer")
    return value


def _positive_int_or_default(value: Any, label: str, *, default: int | None) -> int:
    if value is None:
        if default is None:
            raise SourcePolicyError(f"{label} is required")
        return default
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SourcePolicyError(f"{label} must be a non-negative integer")
    return value


def _required_bool(payload: Mapping[str, Any], key: str, label: str) -> bool:
    if key not in payload:
        raise SourcePolicyError(f"{label} is required")
    return _optional_bool(payload[key], label, default=False)


def _optional_bool(value: Any, label: str, *, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise SourcePolicyError(f"{label} must be a boolean")
    return value


def _validate_source_id(source_id: str) -> None:
    if "://" in source_id or not SOURCE_ID_RE.fullmatch(source_id):
        raise SourcePolicyError("source id must be an explicit safe identifier")


def _validate_source_type(source_type: str) -> None:
    if source_type not in FEED_SOURCE_TYPES:
        raise SourcePolicyError("source type must be feed.rss, feed.atom, or feed.json")


def _validate_archive_source_type(source_type: str) -> None:
    if source_type not in ARCHIVE_SOURCE_TYPES:
        raise SourcePolicyError(
            "source type must be a supported local artifact source type"
        )


def _validate_warc_source_type(source_type: str) -> None:
    if source_type not in WARC_SOURCE_TYPES:
        raise SourcePolicyError("source type must be a supported local WARC source type")


def _validate_policy_status(policy_status: str) -> None:
    if policy_status in BLOCKED_POLICY_STATUSES:
        raise SourcePolicyError(f"source policy status blocks ingestion: {policy_status}")
    if policy_status not in ALLOWED_POLICY_STATUSES:
        raise SourcePolicyError(
            "source policy status must be allowed or allowed_with_limits"
        )


def _validate_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        raise SourcePolicyError("acquisition.url must use http or https")
    if not parsed.netloc:
        raise SourcePolicyError("acquisition.url must include a host")
    if parsed.username or parsed.password:
        raise SourcePolicyError("acquisition.url must not contain credentials")


def _validate_method(method: str) -> None:
    if method.upper() != "GET":
        raise SourcePolicyError("feed acquisition method must be GET")


def _validate_local_artifact_path(path: str) -> None:
    parsed = urllib.parse.urlparse(path)
    if parsed.scheme or path.startswith("//"):
        raise SourcePolicyError("artifact.path must be a local filesystem path")


def _reject_archive_network_fields(payload: Mapping[str, Any]) -> None:
    if "acquisition" in payload:
        raise SourcePolicyError("network acquisition fields are not allowed")
    for dotted_key, value in _flatten_mapping(payload):
        field = dotted_key.rsplit(".", 1)[-1].lower()
        if field in {"url", "urls", "method", "user_agent"}:
            raise SourcePolicyError("network acquisition fields are not allowed")
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            raise SourcePolicyError("network acquisition fields are not allowed")


def _validate_disallowed_flags(payload: Mapping[str, Any]) -> None:
    for dotted_key, value in _flatten_mapping(payload):
        field = dotted_key.rsplit(".", 1)[-1]
        if field in DISALLOWED_TRUE_FLAGS and value is True:
            raise SourcePolicyError(f"{dotted_key} is not allowed for feed ingestion")


def _secret_key_paths(payload: Mapping[str, Any]) -> list[str]:
    paths = []
    for dotted_key, _value in _flatten_mapping(payload):
        field = dotted_key.rsplit(".", 1)[-1].lower()
        if any(marker in field for marker in SECRET_MARKERS):
            paths.append(dotted_key)
    return sorted(set(paths))


def _flatten_mapping(
    payload: Mapping[str, Any],
    *,
    prefix: str = "",
) -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    for key, value in payload.items():
        dotted_key = f"{prefix}.{key}" if prefix else str(key)
        items.append((dotted_key, value))
        if isinstance(value, Mapping):
            items.extend(_flatten_mapping(value, prefix=dotted_key))
    return items


def _artifact_filename(source_type: str) -> str:
    if source_type == "feed.json":
        return "feed.json"
    if source_type == "feed.atom":
        return "atom.xml"
    return "rss.xml"


def _safe_url_summary(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _content_type(headers: Mapping[str, str]) -> str | None:
    for key, value in headers.items():
        if key.lower() == "content-type":
            return value
    return None


def _header_mapping(headers: Any) -> dict[str, str]:
    if hasattr(headers, "items"):
        return {str(key).lower(): str(value) for key, value in headers.items()}
    return {}


def _utc_now() -> datetime:
    return datetime.now(UTC)
