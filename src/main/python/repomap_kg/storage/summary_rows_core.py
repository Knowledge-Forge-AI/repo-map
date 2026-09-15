"""Shared helpers for storage summary row payload decoders."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from repomap_kg.storage.errors import StorageSchemaError


def _count_from_mapping(
    payload: Mapping[str, Any],
    key: str,
    *,
    label: str,
) -> int:
    try:
        return int(payload[key])
    except (KeyError, TypeError, ValueError) as error:
        raise StorageSchemaError(
            f"psql returned a malformed {label}: {key}"
        ) from error


def _required_count_map_from_mapping(
    payload: Mapping[str, Any],
    key: str,
    required_keys: tuple[str, ...],
    *,
    label: str,
) -> dict[str, int]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise StorageSchemaError(f"psql returned a malformed {label}: {key}")
    return {
        required_key: _count_from_mapping(value, required_key, label=label)
        for required_key in required_keys
    }
