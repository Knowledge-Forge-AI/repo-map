"""Strict canonical record bytes shared by every first-use evidence format.

A record is the product's compact, sorted, minimally escaped canonical JSON
(``resource_view._canonical.canonical_bytes``) followed by exactly one LF. A
decoded record must re-encode to identical bytes, hold no duplicate key, no
float or non-finite constant, no integer outside ``0..MAX_COUNTER`` and nest no
deeper than six containers (the root is depth one).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from common_lore_index.ops.resource_view._canonical import (
    CanonicalBoundError,
    canonical_bytes,
)
from first_use_workload_domains import HEX64, MAX_COUNTER, MAX_DEPTH, WorkloadError

_DIGIT_BUDGET = 19


class _Reject(ValueError):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _Reject("malformed")
        result[key] = value
    return result


def _reject_number(_text: str) -> object:
    raise _Reject("malformed")


def _parse_int(text: str) -> int:
    # json.loads supplies a numeric token; no string/bool field is coerced.
    if not text.isascii() or not text.isdigit() or len(text) > _DIGIT_BUDGET:
        raise _Reject("invalid_domain")
    value = int(text)
    if value > MAX_COUNTER:
        raise _Reject("invalid_domain")
    return value


def text_depth_within(text: str, limit: int = MAX_DEPTH) -> bool:
    """Scan JSON text without parsing so deep input never reaches the parser."""
    depth = 0
    in_string = escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > limit:
                return False
        elif character in "]}":
            depth -= 1
    return True


def _check_values(item: object, depth: int = 1) -> None:
    if isinstance(item, bool) or item is None or isinstance(item, str):
        return
    if isinstance(item, int):
        if item < 0 or item > MAX_COUNTER:
            raise WorkloadError("invalid_domain")
        return
    if isinstance(item, list):
        if depth > MAX_DEPTH:
            raise WorkloadError("malformed")
        for value in item:
            _check_values(value, depth + 1)
        return
    if isinstance(item, dict):
        if depth > MAX_DEPTH:
            raise WorkloadError("malformed")
        for key, value in item.items():
            if not isinstance(key, str):
                raise WorkloadError("malformed")
            _check_values(value, depth + 1)
        return
    raise WorkloadError("malformed")


def encode_record(payload: Mapping[str, Any], max_bytes: int) -> bytes:
    """Encode one record object; the bound includes the final LF."""
    if not isinstance(payload, dict):
        raise WorkloadError("malformed")
    _check_values(payload)
    try:
        return canonical_bytes(payload, max_bytes - 1) + b"\n"
    except CanonicalBoundError:
        raise WorkloadError("too_large") from None
    except ValueError:
        raise WorkloadError("malformed") from None


def decode_record(data: bytes, max_bytes: int) -> dict[str, Any]:
    """Decode exact record bytes or raise one closed category."""
    if not isinstance(data, bytes):
        raise WorkloadError("malformed")
    if len(data) > max_bytes:
        raise WorkloadError("too_large")
    if not data.endswith(b"\n") or data.count(b"\n") != 1:
        raise WorkloadError("not_canonical")
    try:
        text = data[:-1].decode("utf-8")
    except UnicodeDecodeError:
        raise WorkloadError("malformed") from None
    if not text_depth_within(text):
        raise WorkloadError("malformed")
    try:
        payload = json.loads(
            text, object_pairs_hook=_pairs, parse_float=_reject_number,
            parse_int=_parse_int, parse_constant=_reject_number,
        )
    except _Reject as error:
        raise WorkloadError(error.category) from None
    except (ValueError, RecursionError):
        raise WorkloadError("malformed") from None
    if type(payload) is not dict:
        raise WorkloadError("malformed")
    if encode_record(payload, max_bytes) != data:
        raise WorkloadError("not_canonical")
    return payload


def closed(raw: object, keys: Sequence[str] | frozenset[str]) -> dict[str, Any]:
    """Require a JSON object holding exactly ``keys``."""
    if type(raw) is not dict or set(raw) != set(keys):
        raise WorkloadError("malformed")
    return raw


def is_count(value: object) -> bool:
    return type(value) is int and 0 <= value <= MAX_COUNTER


def is_hex64(value: object) -> bool:
    return type(value) is str and HEX64.fullmatch(value) is not None


def require(condition: bool, category: str = "invalid_domain") -> None:
    if not condition:
        raise WorkloadError(category)


def string_list(raw: object, *, allowed: Sequence[str] | None = None) -> list[str]:
    require(type(raw) is list, "malformed")
    assert isinstance(raw, list)
    require(all(type(item) is str for item in raw), "malformed")
    if allowed is not None:
        require(all(item in allowed for item in raw))
    return list(raw)


__all__ = [
    "closed", "decode_record", "encode_record", "is_count", "is_hex64", "require",
    "string_list", "text_depth_within",
]
