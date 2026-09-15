"""Validation and payload sanitization helpers for the RepoMap MCP server."""

from __future__ import annotations

import os
from typing import Any

from repomap_kg.graph.keys import parse_key
from repomap_kg.ops.config import PRIVATE_PRIVACY
from repomap_kg.server.ops import (
    readback_path_markers,
    sanitize_jsonable,
)

_CANONICAL_IDENTITY_FIELDS = frozenset(
    {
        "canonical_key",
        "source_key",
        "target_key",
        "evidence_key",
        "identity_metadata_hash",
        "payload_hash",
        "source_id",
    }
)


class RepoMapMcpError(ValueError):
    """Raised when MCP arguments are invalid or storage readback fails."""


def private_storage_payload(connection: Any, payload: Any) -> Any:
    """Redact configured private markers at the MCP presentation boundary."""
    context = connection.ops_context
    if context is None or context.graph.privacy not in PRIVATE_PRIVACY:
        return payload
    return _sanitize_private_storage_payload(
        payload,
        private_markers=readback_path_markers(context),
    )


def _sanitize_private_storage_payload(
    payload: Any,
    *,
    private_markers: tuple[str, ...],
) -> Any:
    if isinstance(payload, dict):
        return {
            str(key): (
                value
                if str(key) in _CANONICAL_IDENTITY_FIELDS
                else _sanitize_private_storage_payload(
                    value,
                    private_markers=private_markers,
                )
            )
            for key, value in payload.items()
        }
    if isinstance(payload, (list, tuple)):
        return [
            _sanitize_private_storage_payload(
                value,
                private_markers=private_markers,
            )
            for value in payload
        ]
    return sanitize_jsonable(payload, private_markers=private_markers)


def validate_source_id_arg(source_id: str) -> str:
    value = require_non_blank(source_id, "source_id")
    if "://" in value:
        raise RepoMapMcpError("source_id must not be a URL")
    if any(character.isspace() for character in value):
        raise RepoMapMcpError("source_id must not contain whitespace")
    return value


def validate_feed_item_key(item_key: str) -> None:
    value = require_non_blank(item_key, "item_key")
    try:
        parsed = parse_key(value)
    except Exception as error:
        raise RepoMapMcpError(f"invalid feed item canonical key: {error}") from error
    if parsed.namespace != "feed.item":
        raise RepoMapMcpError("item_key must use the feed.item namespace")


def _validate_bounded_limit(limit: int, *, max_limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError) as error:
        raise RepoMapMcpError("limit must be a positive integer") from error
    if value < 1 or value > max_limit:
        raise RepoMapMcpError(f"limit must be between 1 and {max_limit}")
    return value


def validate_limit(limit: int) -> int:
    return _validate_bounded_limit(limit, max_limit=500)


def validate_canonical_limit(limit: int) -> int:
    return _validate_bounded_limit(limit, max_limit=200)


def validate_read_schema_version(version: int) -> int:
    if not isinstance(version, int) or isinstance(version, bool) or version not in (0, 1):
        raise RepoMapMcpError("result schema version must be 0 or 1")
    return version


def validate_offset(offset: int) -> int:
    try:
        value = int(offset)
    except (TypeError, ValueError) as error:
        raise RepoMapMcpError("offset must be a non-negative integer") from error
    if value < 0:
        raise RepoMapMcpError("offset must be a non-negative integer")
    return value


def validate_optional_text_filter(value: str | None, label: str) -> None:
    if value is None:
        return
    require_non_blank(value, label)
    if "://" in value:
        raise RepoMapMcpError(f"{label} must not be a URL")


def validate_identity_metadata(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RepoMapMcpError("identity_metadata must be a JSON object")
    return dict(value)


def require_non_blank(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RepoMapMcpError(f"{name} is required")
    return value


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def first_config_value(
    explicit_value: Any,
    environment_name: str,
    *,
    default: str | None = None,
) -> str | None:
    return (
        optional_text(explicit_value)
        or optional_text(os.environ.get(environment_name))
        or default
    )


def validate_psql_command(command: str) -> None:
    if any(character.isspace() for character in command):
        raise RepoMapMcpError("psql_command must not contain whitespace")
    if os.path.basename(command) != "psql":
        raise RepoMapMcpError("psql_command must name a psql executable")
