"""Canonical record bytes for installed-experience evidence over the shared JSON leaf.

The installed formats reuse the unchanged first-use record leaf
(``first_use_workload_encoding``: compact, sorted, minimally escaped canonical
JSON plus one LF, no floats, no negative integers, depth at most six) and only
translate its closed categories into the installed vocabulary.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from first_use_workload_domains import WorkloadError
from first_use_workload_encoding import decode_record, encode_record
from installed_experience_domains import HEX32, HEX64, MAX_TEXT, InstalledError

_CATEGORY = {
    "too_large": "bound-exceeded",
    "unbounded": "bound-exceeded",
    "unsafe_input": "unsafe-member",
    "unreadable": "unreadable",
}


def _translate(error: WorkloadError) -> InstalledError:
    return InstalledError(_CATEGORY.get(error.category, "malformed"))


def encode(payload: Mapping[str, Any], limit: int) -> bytes:
    """Encode one record; the bound includes the final LF."""
    try:
        return encode_record(dict(payload), limit)
    except WorkloadError as error:
        raise _translate(error) from None


def decode(data: bytes, limit: int) -> dict[str, Any]:
    """Decode exact canonical bytes or raise one closed installed category."""
    try:
        return decode_record(data, limit)
    except WorkloadError as error:
        raise _translate(error) from None


def require(condition: bool, category: str = "malformed") -> None:
    if not condition:
        raise InstalledError(category)


def closed(raw: object, keys: Sequence[str] | frozenset[str]) -> dict[str, Any]:
    """Require a JSON object holding exactly ``keys``."""
    if type(raw) is not dict or set(raw) != set(keys):
        raise InstalledError("malformed")
    return raw


def is_count(value: object) -> bool:
    return type(value) is int and value >= 0


def is_hex64(value: object) -> bool:
    return type(value) is str and HEX64.fullmatch(value) is not None


def is_hex32(value: object) -> bool:
    return type(value) is str and HEX32.fullmatch(value) is not None


def is_scalar(value: object) -> bool:
    """A fact value: null, bool, non-negative integer or short printable text."""
    if value is None or type(value) is bool or is_count(value):
        return True
    if type(value) is not str or len(value) > MAX_TEXT:
        return False
    return all(character == "\n" or 32 <= ord(character) < 127 for character in value)


__all__ = ["closed", "decode", "encode", "is_count", "is_hex32", "is_hex64", "is_scalar", "require"]
