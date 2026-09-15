"""Typed canonical encoding for TEST-COV5K-R2 qualification authority."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
import hashlib
import json
import math
from typing import TypeAlias


CanonicalScalar: TypeAlias = bool | int | float | str | None
CanonicalValue: TypeAlias = (
    CanonicalScalar
    | tuple["CanonicalValue", ...]
    | list["CanonicalValue"]
    | Mapping[str, "CanonicalValue"]
)


class CanonicalEncodingError(ValueError):
    """A value cannot participate in qualification authority."""


def _mapping_items(value: Mapping[object, object]) -> list[tuple[object, object]]:
    """Read keys once and reject duplicate keys exposed by custom mappings."""

    items: list[tuple[object, object]] = []
    seen: set[str] = set()
    try:
        keys = list(value.keys())
    except Exception as error:  # pragma: no cover - defensive hostile mapping
        raise CanonicalEncodingError("mapping keys are unreadable") from error
    for key in keys:
        encoded_key = json.dumps(
            _typed(key), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        if encoded_key in seen:
            raise CanonicalEncodingError("mapping contains a duplicate key")
        seen.add(encoded_key)
        items.append((key, value[key]))
    return items


def _typed(value: object) -> object:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "bool", "value": value}
    if isinstance(value, int):
        return {"type": "int", "value": str(value)}
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalEncodingError("non-finite floats are prohibited")
        return {"type": "float", "value": value.hex()}
    if isinstance(value, str):
        return {"type": "str", "value": value}
    if isinstance(value, tuple):
        return {"type": "tuple", "items": [_typed(item) for item in value]}
    if isinstance(value, list):
        return {"type": "list", "items": [_typed(item) for item in value]}
    if isinstance(value, Mapping):
        encoded_items = [
            (_typed(key), _typed(item)) for key, item in _mapping_items(value)
        ]
        encoded_items.sort(
            key=lambda pair: json.dumps(
                pair[0], sort_keys=True, separators=(",", ":"), allow_nan=False
            )
        )
        return {
            "type": "mapping",
            "items": [
                {"key": key, "value": item} for key, item in encoded_items
            ],
        }
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "type": "record",
            "class": f"{type(value).__module__}.{type(value).__qualname__}",
            "fields": [
                {"name": field.name, "value": _typed(getattr(value, field.name))}
                for field in fields(value)
            ],
        }
    if isinstance(value, (set, frozenset)):
        raise CanonicalEncodingError("sets are prohibited")
    raise CanonicalEncodingError(
        f"unsupported canonical type: {type(value).__module__}.{type(value).__qualname__}"
    )


def canonical_bytes(value: object) -> bytes:
    """Encode value with explicit type and ordering authority."""

    return json.dumps(
        _typed(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def canonical_digest(value: object) -> str:
    """Return the SHA-256 digest of the typed canonical form."""

    return hashlib.sha256(canonical_bytes(value)).hexdigest()
