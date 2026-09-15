"""Configuration value validation for bulk ingestion."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from repomap_kg.ops.ingestion.bulk_records import BulkPolicyError


def resolve_config_root(config_path: Path, configured: str) -> Path:
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = config_path.parent / path
    return path.resolve()


def required_table(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise BulkPolicyError(f"{key} table is required")
    return value


def table(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key, {})
    if not isinstance(value, Mapping):
        raise BulkPolicyError(f"{key} table must be an object")
    return value


def required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BulkPolicyError(f"{key} is required")
    return value.strip()


def optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise BulkPolicyError("optional string field must be a string")
    return value


def required_positive_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise BulkPolicyError(f"{key} must be a positive integer")
    return value


def required_bool(payload: Mapping[str, Any], key: str) -> bool:
    if key not in payload:
        raise BulkPolicyError(f"{key} is required")
    return bool_value(payload[key], key)


def bool_value(value: object, key: str) -> bool:
    if not isinstance(value, bool):
        raise BulkPolicyError(f"{key} must be a boolean")
    return value


def string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise BulkPolicyError("list field must be an array")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise BulkPolicyError("list field values must be non-empty strings")
        result.append(item.strip())
    return tuple(result)


def normalized_path_tuple(value: object) -> tuple[str, ...]:
    return tuple(Path(item).as_posix().strip("/") for item in string_tuple(value))
