"""Pure SQL helper utilities for RepoMap storage."""

from __future__ import annotations

from repomap_kg.graph.keys import GraphKeyError, file_key
from repomap_kg.storage.errors import StorageSchemaError

__all__ = (
    "positive_limit",
    "require_supported_graph_key_version",
    "canonical_file_path_prefix",
    "sql_like_prefix_literal",
    "sql_literal",
    "sql_bool",
    "sql_int_or_null",
)


def positive_limit(limit: int) -> int:
    try:
        parsed = int(limit)
    except (TypeError, ValueError) as error:
        raise StorageSchemaError("limit must be a positive integer") from error
    if parsed < 1:
        raise StorageSchemaError("limit must be a positive integer")
    return parsed


def require_supported_graph_key_version(graph_key_version: int) -> None:
    if graph_key_version != 1:
        raise StorageSchemaError("unsupported graph key version")


def canonical_file_path_prefix(path_prefix: str) -> str:
    try:
        normalized = path_prefix.replace("\\", "/")
        stripped = normalized.rstrip("/")
        if stripped in ("", "."):
            return "file:"
        key = file_key(stripped)
        if key == "file:.":
            return "file:"
        return key + "/"
    except GraphKeyError as error:
        raise StorageSchemaError("invalid canonical file path prefix") from error


def sql_like_prefix_literal(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return sql_literal(escaped + "%")


def sql_literal(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def sql_bool(value: bool) -> str:
    return "true" if value else "false"


def sql_int_or_null(value: int | None) -> str:
    return str(value) if value is not None else "NULL"
